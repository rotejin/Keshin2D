// 開きと視線をばねで追い、遅れと行きすぎを瞳の形だけに使う。
// その場で止めると、半目や横を見たままでも、元の瞳の形へ戻る。
function spring(frequency, damping) {
  const omega = 2 * Math.PI * frequency, drag = damping * omega;
  const rate = Math.sqrt(omega * omega - drag * drag);
  let previous, value = 0, velocity = 0;
  return (target, dt) => {
    if (previous === undefined || !(dt > 0 && dt <= 0.12)) {
      previous = value = target;
      velocity = 0;
      return 0;
    }
    // 入力は前のコマから直線でつなぎ、減衰振動の式をその区間で解く。
    const speed = (target - previous) / dt, lag = 2 * damping * speed / omega;
    const y = value - previous + lag, v = velocity - speed;
    const fade = Math.exp(-drag * dt), sine = Math.sin(rate * dt), cosine = Math.cos(rate * dt);
    const offset = fade * (y * cosine + (v + drag * y) * sine / rate);
    velocity = speed + fade * (v * cosine - (drag * v + omega * omega * y) * sine / rate);
    previous = target;
    value = target - lag + offset;
    return value - target;
  };
}

const clamp = (v, low, high) => Math.min(high, Math.max(low, v));
const ease = (from, to, dt, time) => from + (to - from) * -Math.expm1(-dt / time);

function oscillator(omega, damping) {
  const decay = omega * damping, frequency = Math.sqrt(omega * omega - decay * decay);
  return (state, target, dt) => {
    const error = state.value - target;
    const sin = Math.sin(frequency * dt), cos = Math.cos(frequency * dt);
    const envelope = Math.exp(-decay * dt);
    state.value = target + envelope * (error * cos + (state.velocity + decay * error) / frequency * sin);
    state.velocity = envelope * (state.velocity * cos - (decay * state.velocity + omega * omega * error) * sin / frequency);
  };
}

// Easy2D の既定の瞳の動き。開きと視線を別々に追って、瞳の形とレンズの中心を動かす。
export function createIrisSpring() {
  const stepLid = oscillator(2 * Math.PI * 4.2, 0.37);
  const stepGaze = oscillator(1.9 / 0.045, 0.52);
  const lid = { value: 0, velocity: 0 };
  const horizontal = { previous: 0, speed: 0, value: 0, velocity: 0 };
  const vertical = { previous: 0, speed: 0, value: 0, velocity: 0 };
  const output = {};
  let fresh = true, lensPressure = 0, lensX = 0, lensY = 0;

  function gazeBend(axis, position, dt) {
    const speed = (position - axis.previous) / Math.max(dt, 1 / 240);
    axis.previous = position;
    axis.speed = ease(axis.speed, speed, dt, 0.022);
    stepGaze(axis, Math.tanh(axis.speed / 12), dt);
    return clamp(axis.value, -1, 1);
  }

  return (opening, gazeX, gazeY, dt) => {
    const close = clamp(1 - opening, 0, 1);
    let x = 0, y = 0;
    if (fresh || dt > 0.3) {
      fresh = false;
      lid.value = close;
      lid.velocity = 0;
      horizontal.previous = gazeX;
      vertical.previous = gazeY;
      horizontal.value = horizontal.speed = horizontal.velocity = 0;
      vertical.value = vertical.speed = vertical.velocity = 0;
      lensPressure = 0.34 * close;
      lensX = lensY = 0;
    } else if (dt > 0) {
      stepLid(lid, close, dt);
      x = gazeBend(horizontal, gazeX, dt);
      y = gazeBend(vertical, gazeY, dt);
      lensPressure = ease(lensPressure, 0.34 * close + 1.15 * (lid.value - close), dt, 0.045);
      lensX = ease(lensX, x, dt, 0.024);
      lensY = ease(lensY, y, dt, 0.024);
    } else {
      x = clamp(horizontal.value, -1, 1);
      y = clamp(vertical.value, -1, 1);
    }
    const travel = Math.hypot(x, y);
    const squash = travel > 0.00001 ? 0.12 * Math.min(travel, 1) / (travel * travel) : 0;
    const cross = -squash * x * y || 0;
    const pressure = clamp(close + clamp(lid.value - close, -0.36, 0.36) * 100 * 0.015, -1.26, 2.68);
    const sx = 1 + 0.10 * pressure - squash * x * x;
    const sy = Math.max(0.25, 1 - 0.30 * pressure - squash * y * y);
    const shearX = 0.22 * x + cross;
    const shearY = cross;
    const visibleAt = clamp((close - 0.60) / 0.40, 0, 1);
    const visible = 1 - visibleAt * visibleAt * (3 - 2 * visibleAt);
    const upper = visible * 0.55 * Math.tanh(lensPressure / 0.55);
    const warpX = Math.tanh(visible * lensX), warpY = Math.tanh(visible * lensY);
    const warpActive = Math.max(Math.abs(upper), Math.abs(visible * lensX), Math.abs(visible * lensY)) > 0.00001;
    const shapeActive = Math.max(Math.abs(sx - 1), Math.abs(sy - 1), Math.abs(shearX), Math.abs(shearY)) >= 0.0001;
    output.sx = shapeActive ? sx : 1;
    output.sy = shapeActive ? sy : 1;
    output.shearX = shapeActive ? shearX : 0;
    output.shearY = shapeActive ? shearY : 0;
    output.cx = 0.24 * warpX;
    output.cy = 0.24 * warpY;
    output.lens = warpActive ? -0.70 * Math.tanh(2.2 * upper + 0.78 * (warpX * warpX + warpY * warpY)) : 0;
    return output;
  };
}

export function applyIrisSpring(shape, radiusX, radiusY, x, y, out) {
  const cx = radiusX * shape.cx, cy = radiusY * shape.cy;
  const dx = x - cx, dy = y - cy;
  const radius = (dx / (radiusX * 1.60)) ** 2 + (dy / (radiusY * 1.60)) ** 2;
  const scale = 1 + shape.lens * Math.max(0, 1 - radius) ** 3;
  const lx = cx + dx * scale, ly = cy + dy * scale;
  out[0] = lx * shape.sx + ly * shape.shearX;
  out[1] = ly * shape.sy + lx * shape.shearY;
}

export function createLashSpring() {
  const lid = spring(5.4, 0.61);
  return (opening, dt) => {
    const open = Math.min(1.2, Math.max(0, opening));
    const offset = lid(open, dt);
    const t = Math.min(1, open / 0.18);
    const visible = t * t * (3 - 2 * t);
    return Math.min(1.2, Math.max(0, open + visible * 0.085 * Math.tanh(5 * offset)));
  };
}
