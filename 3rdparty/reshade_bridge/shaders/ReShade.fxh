/*
 * ReShade.fxh -- minimal stand-in covering only what our 3 .fx files
 * actually use:
 *   BackBufferExport.fx  -> BUFFER_WIDTH / BUFFER_HEIGHT, ReShade::BackBuffer, PostProcessVS
 *   DepthToAddon.fx      -> same + ReShade::DepthBuffer + pixel size
 *   CaptureStatus.fx     -> BUFFER_*, PostProcessVS
 *
 * Originally part of the unicap repo (which itself vendored upstream
 * ReShade). Lost when we dropped the unicap submodule. This rewrite is
 * intentionally tiny -- if any of our shaders later need more (e.g.
 * stencil access, MipMaps, sRGB samplers), expand here.
 */

#pragma once

// BUFFER_WIDTH / BUFFER_HEIGHT are defined by ReShade at compile time as
// the back-buffer pixel dimensions. The runtime injects them via the FX
// preprocessor; this header just provides fallbacks for syntax tooling.
#ifndef BUFFER_WIDTH
#define BUFFER_WIDTH  1920
#endif
#ifndef BUFFER_HEIGHT
#define BUFFER_HEIGHT 1080
#endif

#ifndef BUFFER_RCP_WIDTH
#define BUFFER_RCP_WIDTH  (1.0 / BUFFER_WIDTH)
#endif
#ifndef BUFFER_RCP_HEIGHT
#define BUFFER_RCP_HEIGHT (1.0 / BUFFER_HEIGHT)
#endif

#ifndef BUFFER_PIXEL_SIZE
#define BUFFER_PIXEL_SIZE float2(BUFFER_RCP_WIDTH, BUFFER_RCP_HEIGHT)
#endif

namespace ReShade
{
    // Built-in textures bound by the ReShade runtime. The semantic
    // names (COLOR / DEPTH) are how ReShade maps them.
    texture BackBufferTex : COLOR;
    sampler BackBuffer { Texture = BackBufferTex; };

    texture DepthBufferTex : DEPTH;
    sampler DepthBuffer { Texture = DepthBufferTex; };
}

// Standard ReShade fullscreen triangle vertex shader. Used by every
// post-process effect. Builds a triangle that covers the whole screen
// with texcoord in [0,1].
void PostProcessVS(in uint id : SV_VertexID,
                   out float4 position : SV_Position,
                   out float2 texcoord : TEXCOORD)
{
    texcoord.x = (id == 2) ? 2.0 : 0.0;
    texcoord.y = (id == 1) ? 2.0 : 0.0;
    position = float4(texcoord * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0);
}
