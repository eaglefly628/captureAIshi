using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using BepInEx;
using UnityEngine;

namespace CaptureAIshi
{
    /// <summary>
    /// BepInEx plugin that listens on a TCP socket for camera pose commands.
    /// Used by the captureAIshi Python framework to remotely control Camera.main.
    ///
    /// Protocol: JSON lines over TCP.
    ///   Request:  {"cmd":"set_pose","x":1.0,"y":2.0,"z":3.0,"pitch":0,"yaw":90,"roll":0,"fov":60}
    ///   Response: {"status":"ok"}
    ///
    ///   Request:  {"cmd":"ping"}
    ///   Response: {"status":"pong"}
    /// </summary>
    [BepInPlugin("com.captureAIshi.cameracapture", "CameraCapturePlugin", "1.0.0")]
    public class CameraCapturePlugin : BaseUnityPlugin
    {
        private TcpListener _listener;
        private TcpClient _client;
        private Thread _listenThread;
        private volatile bool _running;

        private Vector3 _targetPosition;
        private Vector3 _targetRotation;
        private float _targetFov = 60f;
        private volatile bool _hasPendingPose;

        private int _port = 9999;

        private void Awake()
        {
            // Read port from config or environment
            var envPort = Environment.GetEnvironmentVariable("CAPTUREAI_PORT");
            if (envPort != null && int.TryParse(envPort, out int p))
                _port = p;

            _running = true;
            _listenThread = new Thread(ListenLoop) { IsBackground = true };
            _listenThread.Start();

            Logger.LogInfo($"CameraCapturePlugin listening on port {_port}");
        }

        private void OnDestroy()
        {
            _running = false;
            _listener?.Stop();
            _client?.Close();
        }

        private void LateUpdate()
        {
            if (!_hasPendingPose) return;

            var cam = Camera.main;
            if (cam == null) return;

            cam.transform.position = _targetPosition;
            cam.transform.eulerAngles = _targetRotation;
            cam.fieldOfView = _targetFov;

            _hasPendingPose = false;
        }

        private void ListenLoop()
        {
            try
            {
                _listener = new TcpListener(IPAddress.Loopback, _port);
                _listener.Start();

                while (_running)
                {
                    if (!_listener.Pending())
                    {
                        Thread.Sleep(50);
                        continue;
                    }

                    _client = _listener.AcceptTcpClient();
                    Logger.LogInfo("Client connected");
                    HandleClient(_client);
                }
            }
            catch (Exception ex)
            {
                if (_running)
                    Logger.LogError($"Listen error: {ex.Message}");
            }
        }

        private void HandleClient(TcpClient client)
        {
            try
            {
                using var stream = client.GetStream();
                using var reader = new StreamReader(stream, Encoding.UTF8);
                using var writer = new StreamWriter(stream, Encoding.UTF8) { AutoFlush = true };

                while (_running && client.Connected)
                {
                    var line = reader.ReadLine();
                    if (line == null) break;

                    var response = ProcessCommand(line.Trim());
                    writer.WriteLine(response);
                }
            }
            catch (Exception ex)
            {
                if (_running)
                    Logger.LogWarning($"Client error: {ex.Message}");
            }
        }

        private string ProcessCommand(string json)
        {
            try
            {
                var data = JsonUtility.FromJson<CameraCommand>(json);

                switch (data.cmd)
                {
                    case "set_pose":
                        _targetPosition = new Vector3(data.x, data.y, data.z);
                        _targetRotation = new Vector3(data.pitch, data.yaw, data.roll);
                        _targetFov = data.fov > 0 ? data.fov : 60f;
                        _hasPendingPose = true;
                        return "{\"status\":\"ok\"}";

                    case "ping":
                        return "{\"status\":\"pong\"}";

                    default:
                        return "{\"status\":\"error\",\"msg\":\"unknown command\"}";
                }
            }
            catch (Exception ex)
            {
                return $"{{\"status\":\"error\",\"msg\":\"{ex.Message}\"}}";
            }
        }

        [Serializable]
        private class CameraCommand
        {
            public string cmd;
            public float x, y, z;
            public float pitch, yaw, roll;
            public float fov;
        }
    }
}
