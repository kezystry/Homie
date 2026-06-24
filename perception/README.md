# Perception node

The edge. Runs on the Raspberry Pi + Hailo accelerator in the sensor head.

- Drives the thermal, radar, and camera sensors.
- Runs vision inference at the edge (Frigate, object detection).
- Fuses the streams and publishes **normalized events** (zone, occupancy,
  motion, presence confidence) over the encrypted mesh to the core.

Raw imagery stays here; only structured events cross to the reasoning node. This
keeps latency-sensitive inference local and the network quiet.
