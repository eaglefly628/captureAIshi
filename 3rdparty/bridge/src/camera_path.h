/*
 * camera_path.h -- Keyframe camera path with Catmull-Rom + SLERP
 *
 * Implements UUU/IGCS-style camera paths:
 *   - Record keyframe nodes (position, rotation, FOV, timestamp)
 *   - Playback with smooth interpolation
 *   - Catmull-Rom spline for position (C1 continuous)
 *   - SLERP for rotation quaternions (no gimbal lock)
 *   - Linear interpolation for FOV
 *   - Variable speed control
 *
 * TCP commands:
 *   __path_add                  Add current camera as keyframe
 *   __path_add X Y Z P Y R F   Add explicit keyframe
 *   __path_clear                Clear all keyframes
 *   __path_delete N             Delete keyframe N (0-based)
 *   __path_list                 List all keyframes
 *   __path_play [speed]         Start playback (default speed 1.0)
 *   __path_stop                 Stop playback
 *   __path_pause                Pause/resume playback
 *   __path_loop [0|1]           Toggle loop mode
 *   __path_visualize            Dump interpolated path points
 *   __path_capture [interval]   Play path and trigger capture at interval
 *
 * ASCII only (MSVC C4819 compliance).
 */

#ifndef CAPTUREAI_CAMERA_PATH_H
#define CAPTUREAI_CAMERA_PATH_H

#include <vector>
#include <string>
#include <atomic>
#include <mutex>
#include <cmath>
#include <cstdio>

/* Forward-declare from bridge.cpp */
extern void bridge_log(const char* fmt, ...);

/* ── Math helpers ────────────────────────────────────────────────── */

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static inline float deg2rad(float d) { return d * (float)(M_PI / 180.0); }
static inline float rad2deg(float r) { return r * (float)(180.0 / M_PI); }
static inline float lerp_f(float a, float b, float t) { return a + (b - a) * t; }
static inline float clamp_f(float v, float lo, float hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

/* ── Quaternion (for rotation interpolation) ─────────────────────── */

struct Quat {
    float w, x, y, z;

    static Quat identity() { return {1, 0, 0, 0}; }

    /* Euler angles (degrees) to quaternion.
     * Order: Yaw(Y) -> Pitch(X) -> Roll(Z)  (YXZ intrinsic)
     * Matches Python euler_to_quaternion() in core/waypoint.py. */
    static Quat from_euler(float pitch_deg, float yaw_deg, float roll_deg)
    {
        float hp = deg2rad(pitch_deg) * 0.5f;
        float hy = deg2rad(yaw_deg) * 0.5f;
        float hr = deg2rad(roll_deg) * 0.5f;

        float sp = sinf(hp), cp = cosf(hp);
        float sy = sinf(hy), cy = cosf(hy);
        float sr = sinf(hr), cr = cosf(hr);

        /* YXZ rotation order (same as Python waypoint.py) */
        Quat q;
        q.w = cp * cy * cr + sp * sy * sr;
        q.x = sp * cy * cr + cp * sy * sr;
        q.y = cp * sy * cr - sp * cy * sr;
        q.z = cp * cy * sr - sp * sy * cr;
        return q;
    }

    /* Quaternion to Euler angles (degrees), YXZ convention.
     * Inverse of from_euler above. */
    void to_euler(float& pitch, float& yaw, float& roll) const
    {
        /* Pitch (X) = asin(2(wy - xz)) -- note: YXZ has different sign */
        float sinp = 2.0f * (w * x - z * y);
        if (fabsf(sinp) >= 1.0f)
            pitch = rad2deg(copysignf((float)(M_PI / 2.0), sinp));
        else
            pitch = rad2deg(asinf(sinp));

        /* Yaw (Y) = atan2(2(wy + xz), 1 - 2(x^2 + y^2)) */
        yaw = rad2deg(atan2f(
            2.0f * (w * y + x * z),
            1.0f - 2.0f * (x * x + y * y)));

        /* Roll (Z) = atan2(2(wz + xy), 1 - 2(x^2 + z^2)) */
        roll = rad2deg(atan2f(
            2.0f * (w * z + x * y),
            1.0f - 2.0f * (x * x + z * z)));
    }

    float dot(const Quat& o) const {
        return w * o.w + x * o.x + y * o.y + z * o.z;
    }

    float length() const { return sqrtf(dot(*this)); }

    Quat normalized() const {
        float len = length();
        if (len < 1e-8f) return identity();
        return { w / len, x / len, y / len, z / len };
    }

    Quat operator-() const { return { -w, -x, -y, -z }; }
};

/* Spherical Linear Interpolation (SLERP) */
static inline Quat slerp(const Quat& a, const Quat& b_in, float t)
{
    Quat b = b_in;
    float dot = a.dot(b);

    /* Ensure shortest path */
    if (dot < 0.0f) {
        b = -b;
        dot = -dot;
    }

    /* If very close, use linear interpolation to avoid div-by-zero */
    if (dot > 0.9995f) {
        Quat r = {
            lerp_f(a.w, b.w, t),
            lerp_f(a.x, b.x, t),
            lerp_f(a.y, b.y, t),
            lerp_f(a.z, b.z, t),
        };
        return r.normalized();
    }

    float theta = acosf(clamp_f(dot, -1.0f, 1.0f));
    float sin_theta = sinf(theta);
    float wa = sinf((1.0f - t) * theta) / sin_theta;
    float wb = sinf(t * theta) / sin_theta;

    return Quat{
        wa * a.w + wb * b.w,
        wa * a.x + wb * b.x,
        wa * a.y + wb * b.y,
        wa * a.z + wb * b.z,
    };
}

/* ── Catmull-Rom Spline (for position interpolation) ─────────────── */

struct Vec3 {
    float x, y, z;

    Vec3 operator+(const Vec3& o) const { return {x+o.x, y+o.y, z+o.z}; }
    Vec3 operator-(const Vec3& o) const { return {x-o.x, y-o.y, z-o.z}; }
    Vec3 operator*(float s) const { return {x*s, y*s, z*s}; }
};

/*
 * Catmull-Rom spline interpolation between p1 and p2.
 * p0 = point before p1, p3 = point after p2.
 * t in [0, 1]: 0 = at p1, 1 = at p2.
 *
 * This gives C1 continuity (smooth tangents at control points).
 */
static inline Vec3 catmull_rom(
    const Vec3& p0, const Vec3& p1,
    const Vec3& p2, const Vec3& p3, float t)
{
    float t2 = t * t;
    float t3 = t2 * t;

    /* Catmull-Rom basis matrix coefficients */
    Vec3 result;
    result.x = 0.5f * ((2.0f * p1.x) +
        (-p0.x + p2.x) * t +
        (2.0f * p0.x - 5.0f * p1.x + 4.0f * p2.x - p3.x) * t2 +
        (-p0.x + 3.0f * p1.x - 3.0f * p2.x + p3.x) * t3);

    result.y = 0.5f * ((2.0f * p1.y) +
        (-p0.y + p2.y) * t +
        (2.0f * p0.y - 5.0f * p1.y + 4.0f * p2.y - p3.y) * t2 +
        (-p0.y + 3.0f * p1.y - 3.0f * p2.y + p3.y) * t3);

    result.z = 0.5f * ((2.0f * p1.z) +
        (-p0.z + p2.z) * t +
        (2.0f * p0.z - 5.0f * p1.z + 4.0f * p2.z - p3.z) * t2 +
        (-p0.z + 3.0f * p1.z - 3.0f * p2.z + p3.z) * t3);

    return result;
}

/* ── Camera Keyframe ─────────────────────────────────────────────── */

struct CameraKeyframe {
    Vec3  pos;                   /* position (UE5 units) */
    float pitch, yaw, roll;     /* rotation (degrees) */
    float fov;                   /* field of view (degrees) */

    /* Duration to NEXT keyframe (seconds). Last keyframe's is ignored. */
    float duration;

    Quat to_quat() const {
        return Quat::from_euler(pitch, yaw, roll);
    }

    void from_quat(const Quat& q) {
        q.to_euler(pitch, yaw, roll);
    }
};

/* ── Interpolated camera state at a given time ───────────────────── */

struct InterpolatedCamera {
    Vec3  pos;
    float pitch, yaw, roll;
    float fov;
};

/* ── Camera Path System ──────────────────────────────────────────── */

class CameraPath {
public:
    /* ── Keyframe management ── */

    void add_keyframe(const CameraKeyframe& kf)
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_keyframes.push_back(kf);
        bridge_log("[PATH] Added keyframe #%zu: pos=(%.1f,%.1f,%.1f) "
                   "rot=(%.1f,%.1f,%.1f) fov=%.1f dur=%.2fs",
                   m_keyframes.size() - 1,
                   kf.pos.x, kf.pos.y, kf.pos.z,
                   kf.pitch, kf.yaw, kf.roll,
                   kf.fov, kf.duration);
    }

    void clear()
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_keyframes.clear();
        stop();
        bridge_log("[PATH] Cleared all keyframes");
    }

    bool delete_keyframe(size_t index)
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (index >= m_keyframes.size()) return false;
        m_keyframes.erase(m_keyframes.begin() + index);
        bridge_log("[PATH] Deleted keyframe #%zu", index);
        return true;
    }

    size_t count() const { return m_keyframes.size(); }

    /* ── Playback control ── */

    void play(float speed = 1.0f)
    {
        if (m_keyframes.size() < 2) {
            bridge_log("[PATH] Need at least 2 keyframes to play");
            return;
        }
        m_speed = speed;
        m_playing = true;
        m_play_paused = false;
        m_play_time = 0.0f;
        bridge_log("[PATH] Playback started (speed=%.2f, %zu keyframes, "
                   "loop=%s)", speed, m_keyframes.size(),
                   m_loop ? "on" : "off");
    }

    void stop()
    {
        m_playing = false;
        m_play_paused = false;
        m_play_time = 0.0f;
    }

    void toggle_pause()
    {
        m_play_paused = !m_play_paused;
        bridge_log("[PATH] Playback %s",
                   m_play_paused ? "paused" : "resumed");
    }

    void set_loop(bool loop) { m_loop = loop; }
    bool is_playing() const { return m_playing && !m_play_paused; }
    bool is_active() const { return m_playing; }

    /* ── Tick: advance time and return interpolated camera ── */

    /*
     * Call this every frame (or at your desired update rate).
     * dt = time since last tick in seconds.
     * Returns true if path is still playing, false if finished.
     * out = interpolated camera state.
     */
    bool tick(float dt, InterpolatedCamera& out)
    {
        if (!m_playing || m_play_paused || m_keyframes.size() < 2)
            return false;

        m_play_time += dt * m_speed;

        float total_dur = total_duration();
        if (m_play_time >= total_dur) {
            if (m_loop) {
                /* Wrap around */
                while (m_play_time >= total_dur)
                    m_play_time -= total_dur;
            } else {
                /* Reached end */
                m_playing = false;
                bridge_log("[PATH] Playback finished");
                /* Set to last keyframe */
                const auto& last = m_keyframes.back();
                out.pos = last.pos;
                out.pitch = last.pitch;
                out.yaw = last.yaw;
                out.roll = last.roll;
                out.fov = last.fov;
                return false;
            }
        }

        /* Find which segment we're in */
        float accumulated = 0.0f;
        size_t seg = 0;
        for (size_t i = 0; i < m_keyframes.size() - 1; i++) {
            float seg_dur = m_keyframes[i].duration;
            if (seg_dur <= 0.0f) seg_dur = 1.0f;  /* safety */
            if (accumulated + seg_dur > m_play_time) {
                seg = i;
                break;
            }
            accumulated += seg_dur;
            seg = i;
        }

        /* Local t within this segment [0, 1] */
        float seg_dur = m_keyframes[seg].duration;
        if (seg_dur <= 0.0f) seg_dur = 1.0f;
        float local_t = (m_play_time - accumulated) / seg_dur;
        local_t = clamp_f(local_t, 0.0f, 1.0f);

        /* Interpolate! */
        out = interpolate(seg, local_t);
        return true;
    }

    /* ── Query ── */

    float total_duration() const
    {
        float dur = 0.0f;
        for (size_t i = 0; i + 1 < m_keyframes.size(); i++) {
            float d = m_keyframes[i].duration;
            dur += (d > 0.0f) ? d : 1.0f;
        }
        return dur;
    }

    /* Format keyframe list as string for TCP response */
    std::string list_keyframes() const
    {
        std::string result;
        char buf[256];
        for (size_t i = 0; i < m_keyframes.size(); i++) {
            const auto& kf = m_keyframes[i];
            snprintf(buf, sizeof(buf),
                     "[%zu] pos=(%.1f,%.1f,%.1f) rot=(%.1f,%.1f,%.1f) "
                     "fov=%.1f dur=%.2fs\n",
                     i, kf.pos.x, kf.pos.y, kf.pos.z,
                     kf.pitch, kf.yaw, kf.roll, kf.fov, kf.duration);
            result += buf;
        }
        if (result.empty()) result = "(no keyframes)\n";
        return result;
    }

    /* Get interpolated points along the entire path for visualization */
    std::vector<InterpolatedCamera> visualize(int samples_per_segment = 10) const
    {
        std::vector<InterpolatedCamera> points;
        if (m_keyframes.size() < 2) return points;

        for (size_t seg = 0; seg + 1 < m_keyframes.size(); seg++) {
            for (int s = 0; s <= samples_per_segment; s++) {
                float t = (float)s / (float)samples_per_segment;
                points.push_back(interpolate(seg, t));
            }
        }
        return points;
    }

    /* Access keyframes (for capture integration) */
    const std::vector<CameraKeyframe>& keyframes() const {
        return m_keyframes;
    }

private:
    std::vector<CameraKeyframe> m_keyframes;
    std::mutex                  m_mutex;

    std::atomic<bool>  m_playing{false};
    std::atomic<bool>  m_play_paused{false};
    std::atomic<bool>  m_loop{false};
    float              m_speed = 1.0f;
    float              m_play_time = 0.0f;  /* seconds into playback */

    /* ── Core interpolation ── */

    InterpolatedCamera interpolate(size_t seg, float t) const
    {
        size_t n = m_keyframes.size();
        if (n < 2 || seg >= n - 1) {
            const auto& kf = m_keyframes[seg < n ? seg : n - 1];
            return { kf.pos, kf.pitch, kf.yaw, kf.roll, kf.fov };
        }

        /* Catmull-Rom needs 4 control points: p0, p1, p2, p3
         * For edge segments, we clamp/mirror the missing points. */
        size_t i0 = (seg > 0) ? seg - 1 : 0;
        size_t i1 = seg;
        size_t i2 = seg + 1;
        size_t i3 = (seg + 2 < n) ? seg + 2 : n - 1;

        const Vec3& p0 = m_keyframes[i0].pos;
        const Vec3& p1 = m_keyframes[i1].pos;
        const Vec3& p2 = m_keyframes[i2].pos;
        const Vec3& p3 = m_keyframes[i3].pos;

        /* Position: Catmull-Rom */
        Vec3 pos = catmull_rom(p0, p1, p2, p3, t);

        /* Rotation: SLERP between keyframe quaternions */
        Quat q1 = m_keyframes[i1].to_quat();
        Quat q2 = m_keyframes[i2].to_quat();
        Quat q = slerp(q1, q2, t);

        float pitch, yaw, roll;
        q.to_euler(pitch, yaw, roll);

        /* FOV: linear interpolation */
        float fov = lerp_f(m_keyframes[i1].fov, m_keyframes[i2].fov, t);

        return { pos, pitch, yaw, roll, fov };
    }
};

/* Global camera path instance */
static CameraPath g_camera_path;

#endif /* CAPTUREAI_CAMERA_PATH_H */
