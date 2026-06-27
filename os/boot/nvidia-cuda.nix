# Homie reasoning node — NVIDIA proprietary driver + CUDA for the RTX 3060.
#
# Topology-independent GPU base. This module is correct whether the box is a
# pure headless cortex (the decided Homie-OS-only end state) OR also a Proton
# gaming desktop later: CUDA needs the kernel module + userspace GL/compute
# libraries, and Proton/Vulkan needs the very same stack plus 32-bit libs — so
# enabling both here costs nothing on a headless box and means a gaming desktop
# needs no second GPU module. Nothing here starts X; `services.xserver.enable`
# stays false in configuration.nix.
#
# Import from configuration.nix:   imports = [ ./hardware-configuration.nix ./nvidia-cuda.nix ];
#
# All options below are valid on nixos-24.11 (pinned in os/boot/flake.nix).
# VM-VALIDATE: this module pulls the proprietary NVIDIA kernel module, which is
# only exercised against real silicon. `nixos-rebuild build-vm` proves the
# config EVALUATES and builds, but the VM has no RTX 3060 — confirm `nvidia-smi`
# and CUDA on the actual hardware at bring-up (see notes at the bottom).
#
# DRIVER vs CUDA TOOLKIT — a deliberate split. The NVIDIA *driver* (everything
# this module enables by default) is cached on cache.nixos.org and installs
# reliably. The *CUDA toolkit* is NOT on the cache for licensing reasons and is
# fetched from developer.download.nvidia.com — a large, flaky download on an
# unstable link. The desktop only needs the toolkit to serve the local LLM
# (Stage 3); movies/Steam (Stages 2/4) need only the driver + Vulkan/GL. So the
# heavy CUDA closure sits behind `homie.gpu.cuda.enable`, which DEFAULTS OFF:
# a driver-only rebuild pulls nothing flaky. Flip it on for the LLM cortex.

{ config, lib, pkgs, ... }:

let
  cfg = config.homie.gpu;
in
{
  # Off by default: pulls cudaPackages.cudatoolkit, a large unfree closure
  # fetched from developer.download.nvidia.com (NOT cached). Leave off for a
  # driver-only system (movies/Steam); turn on only for the LLM cortex (Stage 3).
  options.homie.gpu.cuda.enable =
    lib.mkEnableOption "the heavy CUDA toolkit (nvcc + runtime) for serving the local LLM";

  config = {
  # ---------------------------------------------------------------------------
  # Unfree licence. The NVIDIA driver — and the proprietary userspace half even
  # of the *open* kernel module — is unfree, so nixpkgs must be allowed to build
  # it. mkDefault so a top-level configuration.nix can still override the policy
  # globally without conflicting with this module (topology independence).
  # ---------------------------------------------------------------------------
  nixpkgs.config.allowUnfree = lib.mkDefault true;

  # ---------------------------------------------------------------------------
  # Select the NVIDIA driver as the video driver. The option name is X11-era,
  # but on 24.11 this is the canonical switch that installs the NVIDIA kernel
  # module + udev rules + userspace and is REQUIRED even headless — it gates the
  # whole `hardware.nvidia` machinery. It does NOT start X (services.xserver is
  # disabled in configuration.nix); it only selects which driver gets built in.
  # ---------------------------------------------------------------------------
  services.xserver.videoDrivers = [ "nvidia" ];

  # ---------------------------------------------------------------------------
  # Userspace graphics/compute libraries (libGL, EGL, the GBM/Vulkan ICDs the
  # CUDA + Proton stacks resolve against). Renamed from `hardware.opengl` in
  # 24.05; `hardware.graphics` is the correct 24.11 spelling. enable32Bit pulls
  # the 32-bit libs Proton/Steam needs — harmless on a headless cortex, and it
  # means the SAME base serves a Proton gaming desktop with no further changes.
  # ---------------------------------------------------------------------------
  hardware.graphics = {
    enable = true;
    enable32Bit = true;
  };

  hardware.nvidia = {
    # Driver branch: production (550) — the KNOWN-GOOD display path on this 3060.
    # We tried `latest` (565) for gamescope's Wayland explicit sync, but 565 went
    # "NO SIGNAL" on the HDMI output with BOTH the open AND proprietary kernel
    # modules (system stayed up, reachable over SSH) — a 565/3060 display
    # regression on this kernel, not a config knob. So we stay on production for a
    # reliable console + display. The Wayland flicker under gamescope that 565
    # would have fixed is instead side-stepped by running GUI apps (Stremio) under
    # a minimal X session, where NVIDIA 550 is rock-solid. Revisit a newer driver
    # only if a future one is confirmed to drive this display.
    package = config.boot.kernelPackages.nvidiaPackages.production;

    # Open vs proprietary KERNEL module on Ampere (RTX 3060).
    # Since driver 560 `open` has NO default on 24.11 (type nullOr bool, default
    # null) and MUST be set explicitly. NVIDIA and the NixOS wiki recommend the
    # open module for Turing+ (the 3060 qualifies); CUDA is identical on either.
    # If a specific driver/kernel combo ever regresses on real hardware, this is
    # the one knob to flip to `false` for the known-good proprietary module.
    # VM-VALIDATE: which module loads cleanly is only provable on the 3060.
    #
    # Open module is the known-good display path AT 550 on this 3060 — keep it.
    # (At 565 BOTH open and proprietary lost the HDMI signal, so the module was
    # never the cause there; the 565 driver was. See the driver-branch note.)
    open = true;

    # Kernel modesetting — needed for a working console framebuffer (the only
    # screen Homie uses: pulled camera frames / faces) and required by the open
    # module path. Defaults true for driver >= 535; set explicitly for clarity.
    modesetting.enable = true;

    # Persistence daemon: keeps the driver initialized so the GPU stays ready
    # between LLM wakes instead of cold-starting on every novelty event. The
    # reasoning cortex is episodic (gated to novelty), so this matters for the
    # first-token latency of an on-demand wake.
    nvidiaPersistenced = true;

    # Leave runtime power management OFF: this is a desktop GPU on wall power,
    # not a laptop. Explicit so the intent is on the record.
    powerManagement.enable = false;
    powerManagement.finegrained = false;
  };

  # ---------------------------------------------------------------------------
  # nouveau must not grab the card before the NVIDIA module loads. The nvidia
  # NixOS module already adds nouveau (and nvidiafb) to blacklistedKernelModules
  # when videoDrivers contains "nvidia"; we add `nouveau.modeset=0` as a
  # belt-and-braces kernel param so the open-source driver can't claim KMS even
  # transiently in early boot. (configuration.nix sets the quiet/loglevel
  # params; kernelParams lists merge, so this is additive.)
  # ---------------------------------------------------------------------------
  boot.kernelParams = [ "nouveau.modeset=0" ];
  boot.blacklistedKernelModules = [ "nouveau" ];

  # ---------------------------------------------------------------------------
  # CUDA runtime + tooling for the local LLM (llama.cpp / Ollama on the 3060).
  #
  #  - cudatoolkit       : full toolkit (nvcc, headers, the static/dynamic CUDA
  #                        runtime) — what a from-source llama.cpp build links
  #                        against, and what `Reason`'s deploy-side client needs
  #                        if it compiles CUDA kernels. This is the canonical,
  #                        documented CUDA package on 24.11.
  #  - nvidia-smi        : NOT listed here on purpose — the nvidia NixOS module
  #                        ALREADY adds the driver's `.bin` output (which carries
  #                        nvidia-smi) to environment.systemPackages once
  #                        videoDrivers contains "nvidia". It is the first thing
  #                        bring-up runs to confirm the GPU is live.
  #
  # The actual model server (Ollama via `services.ollama`, or a llama.cpp
  # derivation) is intentionally NOT pinned here — that is a deploy/serving
  # choice that belongs with the Reason client (core/reason.py keeps the LLM
  # seam out of the tested loop). This module only guarantees the CUDA *base*
  # the server will find.
  #
  # NOTE: cudaPackages.cudatoolkit pulls a large unfree closure and is the one
  # heavy build here — expect a long first `nixos-rebuild`. VM-VALIDATE: confirm
  # the closure builds with `nixos-rebuild build-vm` before touching real disk.
  # ---------------------------------------------------------------------------
  environment.systemPackages =
    lib.mkIf cfg.cuda.enable (with pkgs; [ cudaPackages.cudatoolkit ]);

  # ---------------------------------------------------------------------------
  # Make the driver's runtime libraries discoverable to dynamically-linked CUDA
  # binaries (e.g. a downloaded Ollama or a prebuilt llama.cpp) that look for
  # libcuda.so.1 outside the Nix store. On a NixOS-native build this is found via
  # the driver's OpenGL/driver path, but exporting CUDA_PATH gives from-source
  # builds and `nvcc` a stable toolkit root.
  # ---------------------------------------------------------------------------
  environment.variables.CUDA_PATH =
    lib.mkIf cfg.cuda.enable "${pkgs.cudaPackages.cudatoolkit}";
  };
}
