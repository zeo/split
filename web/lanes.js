// waveforms come precomputed from the server as per-bucket peak and rms values

const shape = (value) => Math.min(1, value ** 0.62);

export function drawWave(canvas, peaks, color, strength = 1) {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const pen = canvas.getContext("2d");
  pen.setTransform(ratio, 0, 0, ratio, 0, 0);
  pen.clearRect(0, 0, width, height);
  if (!peaks?.peak?.length) return;

  const middle = height / 2;
  const reach = middle - 3;
  const buckets = peaks.peak.length;
  const columns = Math.max(1, Math.floor(width));
  const dim = getComputedStyle(canvas).getPropertyValue("--wave-dim") || 0.42;

  pen.fillStyle = color;
  for (const [values, alpha] of [[peaks.peak, Number(dim)], [peaks.rms, 1]]) {
    pen.globalAlpha = alpha * strength;
    pen.beginPath();
    for (let column = 0; column < columns; column++) {
      const from = Math.floor((column * buckets) / columns);
      const to = Math.max(from + 1, Math.floor(((column + 1) * buckets) / columns));
      let top = 0;
      for (let i = from; i < to && i < buckets; i++) top = Math.max(top, values[i]);
      const extent = Math.max(0.5, shape(top) * reach);
      pen.rect(column, middle - extent, 1, extent * 2);
    }
    pen.fill();
  }
  pen.globalAlpha = 1;
}

export function formatTime(seconds, precise = false) {
  const safe = Math.max(0, seconds || 0);
  const minutes = Math.floor(safe / 60);
  const rest = safe - minutes * 60;
  const whole = Math.floor(rest).toString().padStart(2, "0");
  return precise ? `${minutes}:${whole}.${Math.floor((rest % 1) * 10)}` : `${minutes}:${whole}`;
}
