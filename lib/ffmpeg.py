"""
ffmpeg detection and auto-building.

Finds an existing ffmpeg with libass support, or compiles one from source.
Required for burning ASS subtitles onto MPEG-2 video.
"""

import os
import shutil
import subprocess


def find_or_build_ffmpeg():
    """Find an ffmpeg binary with libass support, or build one.

    Search order:
    1. /tmp/ffmpeg-custom/ffmpeg (previously built)
    2. /tmp/ffmpeg-7.1.1/ffmpeg (previously built)
    3. System ffmpeg (if it has libass)
    4. Homebrew / system paths
    5. Build from source as last resort

    Returns:
        Path to ffmpeg binary with libass, or None on failure.
    """
    # Check common locations
    candidates = [
        '/tmp/ffmpeg-custom/ffmpeg',
        '/tmp/ffmpeg-7.1.1/ffmpeg',
        shutil.which('ffmpeg'),
        '/opt/homebrew/bin/ffmpeg',
        '/usr/local/bin/ffmpeg',
        '/usr/bin/ffmpeg',
    ]
    for path in candidates:
        if path and os.path.exists(path):
            r = subprocess.run([path, '-filters'], capture_output=True, text=True)
            if 'subtitles' in r.stdout:
                return path

    # Need to build ffmpeg with libass
    print("\n  ffmpeg with libass not found. Building from source...")
    print("  This may take a few minutes on first run.\n")

    build_dir = '/tmp/ffmpeg-build'
    os.makedirs(build_dir, exist_ok=True)

    # Install dependencies based on platform
    import platform
    system = platform.system()

    if system == 'Darwin':
        for dep in ['libass', 'libx264', 'pkgconf']:
            r = subprocess.run(['brew', 'list', dep], capture_output=True)
            if r.returncode != 0:
                print(f"  Installing {dep}...")
                subprocess.run(['brew', 'install', dep], capture_output=True)
    elif system == 'Linux':
        r = subprocess.run(['pkg-config', '--exists', 'libass'], capture_output=True)
        if r.returncode != 0:
            print("  ERROR: libass not found. Install dependencies first:")
            print("    Debian/Ubuntu: sudo apt install libass-dev libx264-dev pkg-config build-essential")
            print("    Fedora: sudo dnf install libass-devel x264-devel pkgconf-pkg-config gcc make")
            return None

    # Download ffmpeg source
    ffmpeg_dir = os.path.join(build_dir, 'ffmpeg-7.1.1')
    if not os.path.exists(ffmpeg_dir):
        print("  Downloading ffmpeg source...")
        subprocess.run(['curl', '-sL', 'https://ffmpeg.org/releases/ffmpeg-7.1.1.tar.xz',
                        '-o', os.path.join(build_dir, 'ffmpeg.tar.xz')], check=True)
        subprocess.run(['tar', 'xf', os.path.join(build_dir, 'ffmpeg.tar.xz'),
                        '-C', build_dir], check=True)

    # Get pkg-config flags for libass
    pkg_config = shutil.which('pkg-config') or shutil.which('pkgconf') or 'pkg-config'
    r = subprocess.run([pkg_config, '--cflags', 'libass'], capture_output=True, text=True)
    ass_cflags = r.stdout.strip()
    r = subprocess.run([pkg_config, '--libs', 'libass'], capture_output=True, text=True)
    ass_libs = r.stdout.strip()

    # Configure
    print("  Configuring ffmpeg...")
    extra_cflags = ass_cflags
    extra_ldflags = ass_libs
    if system == 'Darwin':
        extra_cflags += ' -I/opt/homebrew/include'
        extra_ldflags += ' -L/opt/homebrew/lib'

    configure_args = [
        './configure', '--prefix=/tmp/ffmpeg-custom',
        '--enable-gpl', '--enable-libx264', '--enable-libass',
        f'--extra-cflags={extra_cflags}',
        f'--extra-ldflags={extra_ldflags}',
    ]
    if system == 'Darwin':
        configure_args.extend(['--enable-videotoolbox', '--enable-audiotoolbox'])

    env = os.environ.copy()
    env['PKG_CONFIG'] = pkg_config
    subprocess.run(configure_args, cwd=ffmpeg_dir, capture_output=True, env=env)

    # Build
    print("  Compiling ffmpeg (this takes a few minutes)...")
    cpus = os.cpu_count() or 4
    subprocess.run(['make', f'-j{cpus}'], cwd=ffmpeg_dir, capture_output=True)

    ffmpeg_bin = os.path.join(ffmpeg_dir, 'ffmpeg')
    if os.path.exists(ffmpeg_bin):
        print(f"  Built: {ffmpeg_bin}")
        return ffmpeg_bin

    print("  ERROR: ffmpeg build failed")
    return None
