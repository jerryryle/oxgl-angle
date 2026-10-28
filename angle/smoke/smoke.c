// Smoke test for an oxgl ANGLE bundle: loads libEGL by absolute path, creates a
// headless SwiftShader display (no window system), clears a 4x4 pbuffer to
// green and reads one pixel back.
//
//   smoke <bundle-lib-dir>
//
// Exit status 0 on success; prints the GL_RENDERER string.
#include <stdio.h>
#include <string.h>

#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <EGL/eglext_angle.h>
#include <GLES2/gl2.h>

#ifdef _WIN32
#include <windows.h>
#define LIB_EGL "libEGL.dll"
static void *open_lib(const char *path) { return (void *)LoadLibraryA(path); }
static void *sym(void *lib, const char *name) { return (void *)GetProcAddress((HMODULE)lib, name); }
#else
#include <dlfcn.h>
#ifdef __APPLE__
#define LIB_EGL "libEGL.dylib"
#else
#define LIB_EGL "libEGL.so"
#endif
static void *open_lib(const char *path) { return dlopen(path, RTLD_NOW | RTLD_LOCAL); }
static void *sym(void *lib, const char *name) { return dlsym(lib, name); }
#endif

#define FAIL(...) do { fprintf(stderr, "smoke: " __VA_ARGS__); fputc('\n', stderr); return 1; } while (0)

int main(int argc, char **argv) {
    if (argc != 2) FAIL("usage: smoke <bundle-lib-dir>");

    char path[4096];
    snprintf(path, sizeof path, "%s/%s", argv[1], LIB_EGL);
    void *egl = open_lib(path);
    if (!egl) FAIL("cannot load %s", path);

    PFNEGLGETPROCADDRESSPROC getProc = (PFNEGLGETPROCADDRESSPROC)sym(egl, "eglGetProcAddress");
    if (!getProc) FAIL("eglGetProcAddress missing");
#define LOAD(type, name) type name = (type)getProc(#name); if (!name) FAIL("missing %s", #name)
    LOAD(PFNEGLGETPLATFORMDISPLAYEXTPROC, eglGetPlatformDisplayEXT);
    LOAD(PFNEGLINITIALIZEPROC, eglInitialize);
    LOAD(PFNEGLCHOOSECONFIGPROC, eglChooseConfig);
    LOAD(PFNEGLCREATEPBUFFERSURFACEPROC, eglCreatePbufferSurface);
    LOAD(PFNEGLCREATECONTEXTPROC, eglCreateContext);
    LOAD(PFNEGLMAKECURRENTPROC, eglMakeCurrent);
    LOAD(PFNEGLDESTROYCONTEXTPROC, eglDestroyContext);
    LOAD(PFNEGLDESTROYSURFACEPROC, eglDestroySurface);
    LOAD(PFNEGLTERMINATEPROC, eglTerminate);
    LOAD(PFNEGLGETERRORPROC, eglGetError);
    LOAD(PFNGLCLEARCOLORPROC, glClearColor);
    LOAD(PFNGLCLEARPROC, glClear);
    LOAD(PFNGLREADPIXELSPROC, glReadPixels);
    LOAD(PFNGLGETSTRINGPROC, glGetString);
    LOAD(PFNGLGETERRORPROC, glGetError);

    const EGLint display_attribs[] = {
        EGL_PLATFORM_ANGLE_TYPE_ANGLE, EGL_PLATFORM_ANGLE_TYPE_VULKAN_ANGLE,
        EGL_PLATFORM_ANGLE_DEVICE_TYPE_ANGLE, EGL_PLATFORM_ANGLE_DEVICE_TYPE_SWIFTSHADER_ANGLE,
        EGL_NONE,
    };
    EGLDisplay dpy = eglGetPlatformDisplayEXT(EGL_PLATFORM_ANGLE_ANGLE, NULL, display_attribs);
    if (dpy == EGL_NO_DISPLAY) FAIL("no display (0x%x)", eglGetError());
    if (!eglInitialize(dpy, NULL, NULL)) FAIL("eglInitialize failed (0x%x)", eglGetError());

    const EGLint config_attribs[] = {
        EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE,
    };
    EGLConfig config;
    EGLint n = 0;
    if (!eglChooseConfig(dpy, config_attribs, &config, 1, &n) || n < 1) FAIL("no config");
    const EGLint pbuffer_attribs[] = {EGL_WIDTH, 4, EGL_HEIGHT, 4, EGL_NONE};
    EGLSurface surface = eglCreatePbufferSurface(dpy, config, pbuffer_attribs);
    if (surface == EGL_NO_SURFACE) FAIL("no pbuffer (0x%x)", eglGetError());
    const EGLint context_attribs[] = {EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE};
    EGLContext ctx = eglCreateContext(dpy, config, EGL_NO_CONTEXT, context_attribs);
    if (ctx == EGL_NO_CONTEXT) FAIL("no context (0x%x)", eglGetError());
    if (!eglMakeCurrent(dpy, surface, surface, ctx)) FAIL("eglMakeCurrent failed");

    glClearColor(0.0f, 1.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    unsigned char px[4] = {0};
    glReadPixels(1, 1, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    const char *renderer = (const char *)glGetString(GL_RENDERER);
    printf("GL_RENDERER: %s\n", renderer ? renderer : "(null)");
    int ok = px[0] == 0 && px[1] == 255 && px[2] == 0 && px[3] == 255 && glGetError() == GL_NO_ERROR;
    int swiftshader = renderer && strstr(renderer, "SwiftShader") != NULL;

    eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroyContext(dpy, ctx);
    eglDestroySurface(dpy, surface);
    eglTerminate(dpy);

    if (!ok) FAIL("pixel was %u,%u,%u,%u, expected 0,255,0,255", px[0], px[1], px[2], px[3]);
    if (!swiftshader) FAIL("renderer is not SwiftShader");
    printf("smoke: ok\n");
    return 0;
}
