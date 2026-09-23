import { useEffect, useRef } from "react";
import * as THREE from "three";
import type { ConversionEvent } from "../types";

/** The Seam, as a real flow field.
 *
 * Every converted item is a particle. It spawns on the Tableau side in source
 * ink and travels right. The instant it crosses x = 0 its colour becomes target
 * ink - the colour change *is* the translation, which is the whole thesis made
 * physical. An item that cannot cross decelerates into the seam and joins a
 * drifting cluster there, so the held count has real mass rather than being a
 * number in a box.
 *
 * One THREE.Points with additive blending. No post-processing: additive soft
 * sprites give the glow for a fraction of an EffectComposer's weight.
 */

const SOURCE = new THREE.Color("#4c9aff");
const TARGET = new THREE.Color("#f2c811");
const HELD = new THREE.Color("#ff7a6b");

const SPAN = 26; // world units from spawn to landing
const TRAIL = 5; // points per item - the streak that makes travel legible
const CROSS_SECONDS = 3.1;
const HOLD_SECONDS = 1.5;

const VERT = /* glsl */ `
  attribute float aBirth;
  attribute float aHeld;
  attribute float aLane;
  attribute float aSeed;
  attribute float aTrail;   // 0 = head, 1 = tail end

  uniform float uTime;
  uniform float uSpan;
  uniform float uCross;
  uniform float uHold;

  varying float vCrossed;
  varying float vHeld;
  varying float vFade;
  varying float vFlare;

  // Ease-out so items decelerate as they arrive, like something being placed.
  float easeOut(float t) { return 1.0 - pow(1.0 - t, 3.0); }

  void main() {
    float age = uTime - aBirth - aTrail * 0.055;
    float dur = mix(uCross, uHold, aHeld);
    float t = clamp(age / dur, 0.0, 1.0);
    float p = easeOut(t);

    // Held items stop at the seam; the rest carry on to the Power BI side.
    float endX = mix(uSpan * 0.5, 0.0, aHeld);
    float x = mix(-uSpan * 0.5, endX, p);

    // A settled held particle drifts in place so the cluster stays alive.
    float settle = aHeld * step(0.999, t);
    x += settle * (sin(uTime * 0.55 + aSeed * 6.2831) * 0.5 + (aSeed - 0.5) * 2.4);
    float y = aLane + settle * cos(uTime * 0.42 + aSeed * 6.2831) * 0.8;

    // Depth is driven by the seed, giving a shallow field rather than a plane.
    float z = (aSeed - 0.5) * 3.2;

    // The seam flares as something passes through it: this is the moment the
    // translation happens, so it is the one thing that gets to be bright.
    vFlare = 1.0 - smoothstep(0.0, 2.4, abs(x));

    vCrossed = step(0.0, x) * (1.0 - aHeld);
    vHeld = aHeld;

    // A crossed item dissolves as it lands: it has become a row in the Power BI
    // list, so the particle has done its job. A held item does not dissolve -
    // it is still waiting for a person, so it stays visible at the seam. The
    // difference is the argument, and it also stops the field from drowning
    // the text it sits behind.
    float arrive = 1.0 - smoothstep(0.62, 1.0, t);
    // A settled item is not moving, so it keeps no streak: only the head
    // survives. Without this, 46 held items x 5 trail points stack additively
    // at one spot and blow out to white.
    float settled = mix(1.0, max(0.0, 1.0 - aTrail), settle);
    float persist = mix(arrive, settled * 0.72, aHeld);

    // The tail is dimmer than the head, and nothing shows before it is born.
    vFade = (age < 0.0 ? 0.0 : 1.0) * (1.0 - aTrail * 0.17) * persist;

    vec4 mv = modelViewMatrix * vec4(x, y, z, 1.0);
    float size = (40.0 - aTrail * 5.0 + aSeed * 8.0) * (1.0 + vFlare * 0.7);
    gl_PointSize = size * (12.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;

const FRAG = /* glsl */ `
  precision mediump float;

  uniform vec3 uSource;
  uniform vec3 uTarget;
  uniform vec3 uHeldColor;

  varying float vCrossed;
  varying float vHeld;
  varying float vFade;
  varying float vFlare;

  void main() {
    // Soft round sprite; the falloff is the glow.
    vec2 d = gl_PointCoord - vec2(0.5);
    float r = length(d);
    if (r > 0.5) discard;
    float alpha = pow(1.0 - r * 2.0, 2.2);

    vec3 colour = mix(uSource, uTarget, vCrossed);
    colour = mix(colour, uHeldColor, vHeld);
    colour += vFlare * 0.35;   // the seam adds light, never a third hue

    gl_FragColor = vec4(colour, alpha * 0.95 * vFade);
  }
`;

interface Props {
  /** Events revealed so far. Growing this array spawns particles. */
  revealed: ConversionEvent[];
  /** Restarting the stream clears the field. */
  runId: number;
  reduced: boolean;
}

export function SeamField({ revealed, runId, reduced }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const api = useRef<{
    push(count: number, held: boolean[]): void;
    reset(): void;
  } | null>(null);
  const pushed = useRef(0);

  useEffect(() => {
    const el = host.current;
    if (!el) return;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
    camera.position.z = 22;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    } catch {
      return; // no WebGL: the DOM layer still carries every number
    }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    el.appendChild(renderer.domElement);

    const MAX = 8192;
    const geom = new THREE.BufferGeometry();
    const birth = new Float32Array(MAX);
    const held = new Float32Array(MAX);
    const lane = new Float32Array(MAX);
    const seed = new Float32Array(MAX);
    const trail = new Float32Array(MAX);
    birth.fill(-1e9);

    geom.setAttribute("position", new THREE.BufferAttribute(new Float32Array(MAX * 3), 3));
    geom.setAttribute("aBirth", new THREE.BufferAttribute(birth, 1));
    geom.setAttribute("aHeld", new THREE.BufferAttribute(held, 1));
    geom.setAttribute("aLane", new THREE.BufferAttribute(lane, 1));
    geom.setAttribute("aSeed", new THREE.BufferAttribute(seed, 1));
    geom.setAttribute("aTrail", new THREE.BufferAttribute(trail, 1));
    geom.setDrawRange(0, 0);

    const uniforms = {
      uTime: { value: 0 },
      uSpan: { value: SPAN },
      uCross: { value: CROSS_SECONDS },
      uHold: { value: HOLD_SECONDS },
      uSource: { value: SOURCE },
      uTarget: { value: TARGET },
      uHeldColor: { value: HELD },
    };

    const points = new THREE.Points(
      geom,
      new THREE.ShaderMaterial({
        uniforms,
        vertexShader: VERT,
        fragmentShader: FRAG,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    );
    scene.add(points);

    let count = 0;
    const clock = new THREE.Clock();

    api.current = {
      push(n, flags) {
        for (let i = 0; i < n; i++) {
          const isHeld = flags[i];
          const now = clock.getElapsedTime();
          // A narrow band reads as a stream; a wide scatter reads as noise.
          const y = (Math.random() - 0.5) * (isHeld ? 3.0 : 6.4);
          const s = Math.random();
          for (let t = 0; t < TRAIL && count < MAX; t++) {
            birth[count] = now;
            held[count] = isHeld ? 1 : 0;
            lane[count] = y;
            seed[count] = s;
            trail[count] = t;
            count++;
          }
        }
        geom.setDrawRange(0, count);
        for (const name of ["aBirth", "aHeld", "aLane", "aSeed", "aTrail"]) {
          geom.getAttribute(name).needsUpdate = true;
        }
      },
      reset() {
        count = 0;
        birth.fill(-1e9);
        geom.setDrawRange(0, 0);
      },
    };

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = el;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);

    let raf = 0;
    const tick = () => {
      uniforms.uTime.value = clock.getElapsedTime();
      renderer.render(scene, camera);
      raf = requestAnimationFrame(tick);
    };
    if (reduced) {
      // Motion off: render one frame so the field is present but still.
      uniforms.uTime.value = 1e6;
      renderer.render(scene, camera);
    } else {
      tick();
    }

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      geom.dispose();
      points.material.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
      api.current = null;
    };
  }, [reduced]);

  useEffect(() => {
    api.current?.reset();
    pushed.current = 0;
  }, [runId]);

  useEffect(() => {
    const pending = revealed.length - pushed.current;
    if (pending <= 0 || !api.current) return;
    const slice = revealed.slice(pushed.current);
    api.current.push(
      pending,
      slice.map((e) => e.outcome === "held"),
    );
    pushed.current = revealed.length;
  }, [revealed]);

  return <div ref={host} className="seamfield" aria-hidden="true" />;
}
