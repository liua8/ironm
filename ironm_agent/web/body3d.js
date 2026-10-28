// 3D 肌肉人体图（spec [2026-10-23] §57 需求 3）：拖动转一圈、双指或滚轮缩放、"正面""背面"一键回正，
// 点细分肌肉看详情。颜色按近 7 天组数分四档，恢复中、还酸的肌肉一明一暗地闪；编码表以外的分区画成底色、点不了。
// 模型：Z-Anatomy 健身改造版（CC BY-SA 4.0），显示用 three.js r160（MIT），都由服务端提供，见 THIRD-PARTY.md。
import * as THREE from "./three-r160.module.min.js";
import { GLTFLoader } from "./three-r160-gltf-loader.js";
import { OrbitControls } from "./three-r160-orbit-controls.js";

const MODEL = "/iron/muscles-v1.glb";
const FRONT = 0;
const BACK = Math.PI;
let model = null; // 模型只下载、解析一次，之后每次进数据页复用

export function supported() {
  try {
    const c = document.createElement("canvas");
    return Boolean(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl")));
  } catch {
    return false;
  }
}

function palette() {
  const css = getComputedStyle(document.documentElement);
  const col = (name, fallback) => new THREE.Color(css.getPropertyValue(name).trim() || fallback);
  const surface = col("--surface", "#ffffff"), muted = col("--muted", "#706b62");
  const fire = col("--fire", "#f2561d"), fire2 = col("--fire-2", "#d92b3a");
  const mix = (a, b, t) => a.clone().lerp(b, t);
  return {
    level: { none: mix(surface, muted, 0.32), low: mix(surface, fire, 0.42), mid: mix(surface, fire, 0.8), high: fire2 },
    base: mix(surface, muted, 0.14),
  };
}

// 分区名在网格的节点上；一个分区有几块子肌肉时，名字在上一层
function regionOf(obj, known) {
  for (let o = obj; o; o = o.parent) if (known.has(o.name)) return o.name;
  return null;
}

export async function mount(host, muscles, onPick) {
  model ||= new GLTFLoader().loadAsync(MODEL);
  const gltf = await model;
  const colors = palette();
  const byRegion = new Map();
  for (const m of muscles) for (const r of m.model || []) byRegion.set(r, m);

  const root = gltf.scene.clone(true);
  const pickable = [];
  const pulsing = [];
  const owned = []; // 本次创建的材质，离开页面时释放
  root.traverse((o) => {
    if (!o.isMesh) return;
    const region = regionOf(o, byRegion);
    const m = region ? byRegion.get(region) : null;
    const skin = regionOf(o, new Set(["context_skin"]));
    const mat = new THREE.MeshStandardMaterial({
      color: m ? colors.level[m.level] || colors.level.none : colors.base,
      vertexColors: o.geometry.hasAttribute("color"),
      roughness: 0.62, metalness: 0, side: THREE.DoubleSide,
      transparent: Boolean(skin), opacity: skin ? 0.35 : 1,
    });
    owned.push(mat);
    o.material = mat;
    o.userData.muscle = m;
    if (m) {
      pickable.push(o);
      if (m.state !== "ready") pulsing.push(mat);
    }
  });

  const scene = new THREE.Scene();
  scene.add(root);
  const camera = new THREE.PerspectiveCamera(30, 1, 0.05, 20);
  const DIST = 3.7; // 竖屏时头到脚都在画面里
  camera.position.set(0, 0, DIST);
  scene.add(camera, new THREE.HemisphereLight(0xffffff, 0x8a8178, 1.6));
  const key = new THREE.DirectionalLight(0xffffff, 1.4);
  key.position.set(0.6, 1, 1);
  camera.add(key); // 光跟着视角走，转到背面也是亮的

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  const canvas = renderer.domElement;
  canvas.className = "body3d-canvas";
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "3D 肌肉图：拖动旋转，双指或滚轮缩放，点肌肉看详情");
  host.replaceChildren(canvas);

  const controls = new OrbitControls(camera, canvas);
  controls.target.set(0, 0, 0);
  controls.enablePan = false;
  controls.enableDamping = true;
  controls.dampingFactor = 0.12;
  controls.rotateSpeed = 0.8;
  controls.minDistance = 1.5;
  controls.maxDistance = 5;
  controls.minPolarAngle = Math.PI / 2 - 0.55; // 上下只转有限角度
  controls.maxPolarAngle = Math.PI / 2 + 0.55;

  const size = () => {
    const w = host.clientWidth || 320;
    const h = Math.round(Math.min(460, Math.max(300, w * 1.15)));
    renderer.setSize(w, h, false);
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  size();
  const ro = new ResizeObserver(size);
  ro.observe(host);

  // 正面、背面：转回去，距离和高度也回到初始
  let turn = null;
  const turnTo = (azimuth) => {
    const from = new THREE.Spherical().setFromVector3(camera.position.clone().sub(controls.target));
    let d = azimuth - from.theta;
    d = Math.atan2(Math.sin(d), Math.cos(d));
    turn = { from, d, start: performance.now() };
  };

  // 点一下（不是拖）才算选中
  const ray = new THREE.Raycaster();
  let down = null;
  canvas.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
  canvas.addEventListener("pointerup", (e) => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 6) return;
    const r = canvas.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
    const hit = ray.intersectObjects(root.children, true)[0];
    const m = hit?.object?.userData?.muscle;
    if (m) onPick(m);
  });

  const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches; // 不闪，固定亮一点
  let visible = true;
  const io = new IntersectionObserver(([x]) => { visible = x.isIntersecting; });
  io.observe(host);
  const loop = (now) => {
    if (!canvas.isConnected) { // 离开数据页：释放
      ro.disconnect(); io.disconnect(); controls.dispose();
      for (const m of owned) m.dispose();
      renderer.dispose();
      return;
    }
    requestAnimationFrame(loop);
    if (!visible) return;
    if (turn) {
      const t = Math.min(1, (now - turn.start) / 450), k = t * (2 - t);
      const s = new THREE.Spherical(
        turn.from.radius + (DIST - turn.from.radius) * k,
        turn.from.phi + (Math.PI / 2 - turn.from.phi) * k,
        turn.from.theta + turn.d * k,
      );
      camera.position.setFromSpherical(s).add(controls.target);
      camera.lookAt(controls.target);
      if (t >= 1) turn = null;
    }
    controls.update();
    const glow = still ? 0.35 : 0.08 + 0.2 * (Math.sin(now / 320) + 1); // 用它自己的颜色一明一暗，档位颜色不变
    for (const mat of pulsing) mat.emissive.copy(mat.color).multiplyScalar(glow);
    renderer.render(scene, camera);
  };
  requestAnimationFrame(loop);
  return { front: () => turnTo(FRONT), back: () => turnTo(BACK) };
}
