/**
 * Synthesized Web Audio API Sound Alerts (No external MP3 files needed!)
 */

class AudioAlertManager {
  constructor() {
    this.ctx = null;
    this.enabled = localStorage.getItem("gps_audio_alerts") !== "false";
    this.lastAlertTime = 0;
    this.initAudioContext();
  }

  initAudioContext() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) {
        this.ctx = new AudioCtx();
      }
    } catch (e) {
      console.warn("Web Audio API not supported", e);
    }
  }

  unlock() {
    if (this.ctx && this.ctx.state === "suspended") {
      this.ctx.resume();
    }
  }

  setSound(enabled) {
    this.enabled = !!enabled;
    localStorage.setItem("gps_audio_alerts", this.enabled ? "true" : "false");
    if (this.enabled) {
      this.unlock();
    }
    return this.enabled;
  }

  toggleSound() {
    return this.setSound(!this.enabled);
  }

  /**
   * Waze-style Speed Camera Warning (Double High Ping)
   */
  playSpeedCameraAlert() {
    if (!this.enabled || !this.ctx) return;
    const now = Date.now();
    if (now - this.lastAlertTime < 8000) return; // Prevent spamming
    this.lastAlertTime = now;

    this.unlock();
    const t = this.ctx.currentTime;

    // Ping 1 (880 Hz - A5)
    this._playTone(880, t, 0.18, 0.35);
    // Ping 2 (1174.66 Hz - D6)
    this._playTone(1174.66, t + 0.22, 0.25, 0.4);
  }

  /**
   * Overspeed Warning (Urgent Triple Beep)
   */
  playOverspeedWarning() {
    if (!this.enabled || !this.ctx) return;
    const now = Date.now();
    if (now - this.lastAlertTime < 5000) return;
    this.lastAlertTime = now;

    this.unlock();
    const t = this.ctx.currentTime;
    this._playTone(950, t, 0.1, 0.4);
    this._playTone(950, t + 0.14, 0.1, 0.4);
    this._playTone(950, t + 0.28, 0.15, 0.45);
  }

  /**
   * POI / Junction Cue (Pleasant chime)
   */
  playPoiChime() {
    if (!this.enabled || !this.ctx) return;
    this.unlock();
    const t = this.ctx.currentTime;
    this._playTone(523.25, t, 0.15, 0.25); // C5
    this._playTone(659.25, t + 0.12, 0.25, 0.3); // E5
  }

  _playTone(freq, startTime, duration, gainValue = 0.3) {
    try {
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();

      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, startTime);

      gain.gain.setValueAtTime(0, startTime);
      gain.gain.linearRampToValueAtTime(gainValue, startTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, startTime + duration);

      osc.connect(gain);
      gain.connect(this.ctx.destination);

      osc.start(startTime);
      osc.stop(startTime + duration);
    } catch (e) {}
  }
}

window.audioAlerts = new AudioAlertManager();
