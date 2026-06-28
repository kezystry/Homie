# homie-local.nix — per-box local toggles (a safe, additive drop-in module).
#
# WHY this exists: your live /etc/nixos/configuration.nix controls the bootloader,
# LUKS, and hardware — risky to rewrite. This module only ADDS to options that NixOS
# merges cleanly (systemPackages, the homie service's environment, one new service).
# It never edits boot/disk/hardware, so it is safe to layer onto a working system.
#
# INSTALL (one time):
#   sudo cp /opt/homie/os/boot/homie-local.nix /etc/nixos/
#   # then add  ./homie-local.nix  to the `imports = [ ... ];` line in
#   # /etc/nixos/configuration.nix, and:
#   sudo nixos-rebuild switch
#   ollama pull llama3.2:3b          # download a brain (fast on CPU — proves the loop)
#   sudo systemctl restart homie
#
# After that: the cockpit answers (brain), /close stremio works (hands), and
# /update · /restart run for real (shell commands).
{ pkgs, ... }:
{
  # Tools Homie's hands (xdotool) and a terminal (Claude Code via npx) need.
  environment.systemPackages = [ pkgs.xdotool pkgs.nodejs ];

  # THE BRAIN: a local, OpenAI-compatible model server. Ollama serves
  # /v1/chat/completions on 127.0.0.1:11434 — exactly what Homie's cortex talks to.
  # Pick a model AFTER the rebuild with `ollama pull <name>`:
  #   llama3.2:3b   — small, fast on CPU (good to prove the loop)
  #   qwen2.5:7b    — better reasoning; wants the GPU
  # For RTX 3060 speed, set acceleration = "cuda" ONCE the NVIDIA driver is configured
  # (see os/boot/nvidia-cuda.nix). CPU works out of the box, just slower.
  services.ollama = {
    enable = true;
    # acceleration = "cuda";   # uncomment after the NVIDIA driver is set up
  };

  # Turn on what was OFF. These MERGE with the existing service environment (they do
  # not replace HOMIE_STATE etc.):
  #   HOMIE_DESKTOP*       → /close + media keys (this box runs the screen + Stremio)
  #   HOMIE_SHELL_COMMANDS → /update, /restart, /reboot actually run from chat
  #   HOMIE_LLM_URL/MODEL  → point the cortex at the Ollama brain above
  systemd.services.homie.environment = {
    HOMIE_DESKTOP = "1";
    HOMIE_DESKTOP_DISPLAY = ":0";
    HOMIE_SHELL_COMMANDS = "1";
    HOMIE_LLM_URL = "http://127.0.0.1:11434/v1/chat/completions";
    HOMIE_LLM_MODEL = "llama3.2:3b";
  };
}
