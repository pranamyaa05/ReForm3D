import { Suspense, useMemo, useRef, useEffect } from "react";
import { useReducedMotion } from "framer-motion";
import { Canvas, useFrame, useLoader } from "@react-three/fiber";
import { ContactShadows, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader";
import { buildGearGeometry } from "./partGeometry";

function StudioEnvironment() {
  const texture = useMemo(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 1024;
    canvas.height = 512;
    const ctx = canvas.getContext("2d");
    const base = ctx.createLinearGradient(0, 0, 0, 512);
    base.addColorStop(0, "#364855");
    base.addColorStop(0.42, "#b2c4cb");
    base.addColorStop(0.6, "#dbe7e9");
    base.addColorStop(1, "#435966");
    ctx.fillStyle = base;
    ctx.fillRect(0, 0, 1024, 512);
    const softboxes = [
      [90, 54, 104, 318, "#f4ffff"],
      [366, 24, 148, 205, "#e8fbff"],
      [690, 90, 112, 300, "#ffffff"],
      [900, 45, 62, 250, "#87eaff"],
    ];
    softboxes.forEach(([x, y, w, h, color]) => {
      const gradient = ctx.createLinearGradient(x, y, x + w, y + h);
      gradient.addColorStop(0, "rgba(255,255,255,0)");
      gradient.addColorStop(0.35, color);
      gradient.addColorStop(0.72, color);
      gradient.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = gradient;
      ctx.fillRect(x, y, w, h);
    });
    const map = new THREE.CanvasTexture(canvas);
    map.mapping = THREE.EquirectangularReflectionMapping;
    map.colorSpace = THREE.SRGBColorSpace;
    return map;
  }, []);
  return <primitive object={texture} attach="environment" />;
}

const BOLT_POSITIONS = Array.from({ length: 4 }, (_, i) => {
  const a = (i * Math.PI) / 2 + Math.PI / 4;
  return [Math.cos(a) * 0.58, Math.sin(a) * 0.58, 0];
});

function FadeGroup({ active, children }) {
  const ref = useRef();
  const opacity = useRef(active ? 1 : 0);
  useFrame((_, dt) => {
    opacity.current = THREE.MathUtils.damp(opacity.current, active ? 1 : 0, 4.5, dt);
    const group = ref.current;
    if (!group) return;
    group.visible = opacity.current > 0.015;
    group.scale.setScalar(0.91 + opacity.current * 0.09);
    group.traverse((object) => {
      if (!object.material) return;
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.forEach((material) => {
        if (material.userData.skipFade) return;
        material.opacity = (material.userData.baseOpacity ?? 1) * opacity.current;
      });
    });
  });
  return <group ref={ref} scale={0.8}>{children}</group>;
}

function GlowMaterial({ color = "#58dcff", opacity = 0.8 }) {
  return (
    <meshBasicMaterial
      color={color}
      transparent
      opacity={opacity}
      blending={THREE.AdditiveBlending}
      depthWrite={false}
      toneMapped={false}
    />
  );
}

function HaloSystem({ accent, reducedMotion }) {
  const orbitA = useRef();
  const orbitB = useRef();
  const marker = useRef();
  useFrame(({ clock }, dt) => {
    if (reducedMotion) return;
    const t = clock.elapsedTime;
    orbitA.current.rotation.z += dt * 0.09;
    orbitB.current.rotation.y += dt * 0.07;
    marker.current.position.set(Math.cos(t * 0.45) * 1.88, Math.sin(t * 0.45) * 1.88, -0.42);
  });
  return (
    <group>
      <group ref={orbitA} position={[0, 0, -0.42]}>
        <mesh>
          <torusGeometry args={[1.55, 0.009, 8, 160]} />
          <GlowMaterial color={accent} opacity={0.85} />
        </mesh>
        <mesh rotation={[0.22, 0, 0]}>
          <torusGeometry args={[1.92, 0.005, 6, 160]} />
          <GlowMaterial color="#4abfdf" opacity={0.42} />
        </mesh>
      </group>
      <group ref={orbitB} position={[0, 0, -0.48]} rotation={[0.36, 0.58, 0.16]}>
        <mesh>
          <torusGeometry args={[2.12, 0.004, 6, 160]} />
          <GlowMaterial color="#8997ff" opacity={0.34} />
        </mesh>
      </group>
      <mesh ref={marker} position={[1.88, 0, -0.42]}>
        <sphereGeometry args={[0.038, 16, 16]} />
        <meshBasicMaterial color={accent} toneMapped={false} />
      </mesh>
      <mesh position={[-1.86, 0, -0.42]}>
        <sphereGeometry args={[0.026, 14, 14]} />
        <meshBasicMaterial color="#93f3ff" toneMapped={false} />
      </mesh>
    </group>
  );
}

function FractureFragments() {
  const pieces = useMemo(() => [
    { position: [0.99, 0.18, 0.03], rotation: [0.4, 1.2, 0.3], scale: [0.11, 0.055, 0.07] },
    { position: [1.13, 0.34, -0.06], rotation: [1.1, 0.4, 0.8], scale: [0.075, 0.045, 0.055] },
    { position: [0.92, -0.10, 0.13], rotation: [0.7, 2.1, 0.2], scale: [0.065, 0.04, 0.05] },
  ], []);
  const material = useMemo(() => new THREE.MeshPhysicalMaterial({
    color: "#ff8157",
    emissive: "#e94718",
    emissiveIntensity: 0.38,
    metalness: 0.4,
    roughness: 0.28,
    clearcoat: 0.7,
    transparent: true,
  }), []);
  const geo = useMemo(() => new THREE.TetrahedronGeometry(1, 0), []);
  return pieces.map((piece, i) => (
    <mesh key={i} geometry={geo} material={material} position={piece.position} rotation={piece.rotation} scale={piece.scale} />
  ));
}

function MechanicalDetails({ accent, material, shaftMaterial }) {
  const bronze = useMemo(() => new THREE.MeshPhysicalMaterial({
    color: "#53d5e5", metalness: 0.78, roughness: 0.22,
    clearcoat: 1, clearcoatRoughness: 0.1,
  }), []);
  const dark = useMemo(() => new THREE.MeshPhysicalMaterial({
    color: "#202e3a", metalness: 0.86, roughness: 0.23, clearcoat: 0.8,
  }), []);
  const boltGeo = useMemo(() => new THREE.CylinderGeometry(0.052, 0.052, 0.042, 12), []);
  const washerGeo = useMemo(() => new THREE.TorusGeometry(0.073, 0.009, 8, 28), []);
  const hubGeo = useMemo(() => new THREE.CylinderGeometry(0.285, 0.31, 0.12, 64), []);
  const shaftGeo = useMemo(() => new THREE.CylinderGeometry(0.135, 0.15, 0.92, 48), []);
  const hubRing = useMemo(() => new THREE.TorusGeometry(0.235, 0.018, 10, 72), []);
  const spokeGeo = useMemo(() => new THREE.BoxGeometry(0.31, 0.062, 0.05), []);
  const outerTrim = useMemo(() => new THREE.TorusGeometry(0.695, 0.008, 8, 100), []);
  const innerTrim = useMemo(() => new THREE.TorusGeometry(0.36, 0.007, 8, 80), []);
  const indexGeo = useMemo(() => new THREE.SphereGeometry(0.022, 12, 10), []);
  return (
    <group>
      {/* The stepped hub and through-shaft turn the flat gear into a real assembly. */}
      <mesh geometry={shaftGeo} material={shaftMaterial || dark} rotation={[Math.PI / 2, 0, 0]} />
      <mesh geometry={hubGeo} material={material} rotation={[Math.PI / 2, 0, 0]} position={[0, 0, 0.37]} />
      <mesh geometry={hubRing} position={[0, 0, 0.44]}>
        <GlowMaterial color={accent} opacity={0.95} />
      </mesh>
      <mesh geometry={outerTrim} position={[0, 0, 0.36]}>
        <meshStandardMaterial color="#5e8594" metalness={0.7} roughness={0.28} />
      </mesh>
      <mesh geometry={innerTrim} position={[0, 0, 0.4]}>
        <meshStandardMaterial color="#83e7ef" metalness={0.6} roughness={0.22} emissive="#0a7384" emissiveIntensity={0.22} />
      </mesh>
      {Array.from({ length: 12 }, (_, i) => {
        const a = (i * Math.PI) / 6;
        return (
          <mesh key={`index-${i}`} geometry={indexGeo} material={bronze}
            position={[Math.cos(a) * 0.76, Math.sin(a) * 0.76, 0.36]} />
        );
      })}
      {BOLT_POSITIONS.map((position, i) => {
        const angle = Math.atan2(position[1], position[0]);
        return (
          <mesh key={`spoke-${i}`} geometry={spokeGeo} material={bronze}
            position={[Math.cos(angle) * 0.42, Math.sin(angle) * 0.42, 0.37]}
            rotation={[0, 0, angle]} />
        );
      })}
      <mesh position={[0, 0, 0.44]} rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[0.105, 0.105, 0.022, 40]} />
        <meshPhysicalMaterial color="#132530" metalness={0.8} roughness={0.24} />
      </mesh>
      <mesh position={[0, 0, 0.455]}>
        <torusGeometry args={[0.075, 0.008, 8, 48]} />
        <GlowMaterial color="#b6f6ff" opacity={0.75} />
      </mesh>
      {BOLT_POSITIONS.map((position, i) => (
        <group key={i} position={[position[0], position[1], 0.36]}>
          <mesh geometry={washerGeo} material={bronze} />
          <mesh geometry={boltGeo} material={dark} rotation={[Math.PI / 2, 0, 0]} position={[0, 0, 0.005]} />
          <mesh position={[0, 0, 0.028]}>
            <boxGeometry args={[0.044, 0.009, 0.009]} />
            <meshStandardMaterial color="#74e7ee" metalness={0.7} roughness={0.3} />
          </mesh>
        </group>
      ))}
    </group>
  );
}


function Pinion({ geometry, material, accent, wireframe = false }) {
  const edgeGeometry = useMemo(() => new THREE.EdgesGeometry(geometry, 18), [geometry]);
  return (
    <group position={[1.34, 0.02, 0.015]} rotation={[0.02, 0.04, 0.12]}>
      <mesh geometry={geometry} material={material} castShadow receiveShadow />
      {wireframe && (
        <mesh geometry={geometry}>
          <meshBasicMaterial color={accent} wireframe transparent opacity={0.64} depthWrite={false} />
        </mesh>
      )}
      <lineSegments geometry={edgeGeometry}>
        <lineBasicMaterial color="#284453" transparent opacity={0.5} />
      </lineSegments>
      <mesh position={[0, 0, 0.44]} rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[0.19, 0.22, 0.14, 48]} />
        <meshPhysicalMaterial color="#9fbac4" metalness={0.56} roughness={0.22} clearcoat={0.7} />
      </mesh>
      <mesh position={[0, 0, 0.37]}>
        <torusGeometry args={[0.135, 0.014, 8, 48]} />
        <GlowMaterial color={accent} opacity={0.85} />
      </mesh>
      <mesh position={[0, 0, -0.22]} rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[0.12, 0.14, 0.32, 40]} />
        <meshPhysicalMaterial color="#314957" metalness={0.78} roughness={0.24} />
      </mesh>
    </group>
  );
}

function BrokenStage({ geo, pinionGeo, accent }) {
  const edgeGeometry = useMemo(() => new THREE.EdgesGeometry(geo, 24), [geo]);
  const body = useMemo(() => new THREE.MeshPhysicalMaterial({
    color: "#8ba5b0", metalness: 0.68, roughness: 0.2,
    clearcoat: 1, clearcoatRoughness: 0.12,
    transparent: true,
  }), []);
  const edges = useMemo(() => new THREE.LineBasicMaterial({
    color: "#142530", transparent: true, opacity: 0.46,
  }), []);
  return (
    <group>
      <mesh geometry={geo} material={body} castShadow receiveShadow />
      <lineSegments geometry={edgeGeometry} material={edges} />
      <MechanicalDetails accent={accent} material={body} />
      <Pinion geometry={pinionGeo} material={body} accent={accent} />
      <FractureFragments />
    </group>
  );
}

function ScanSweep({ accent, reducedMotion }) {
  const ref = useRef();
  useFrame(({ clock }) => {
    if (!reducedMotion) {
      const t = clock.elapsedTime;
      ref.current.position.z = 0.4 + Math.sin(t * 1.2) * 0.7;
      ref.current.material.opacity = 0.28 + 0.16 * Math.sin(t * 3.4);
    }
  });
  return (
    <mesh ref={ref} rotation={[0, 0, 0]} position={[0, 0, 0.4]}>
      <torusGeometry args={[1.18, 0.014, 8, 112]} />
      <GlowMaterial color={accent} opacity={0.32} />
    </mesh>
  );
}

function ScanStage({ geo, pinionGeo, accent, reducedMotion }) {
  const fill = useMemo(() => new THREE.MeshBasicMaterial({
    color: "#44d8ef", transparent: true, opacity: 0.09, depthWrite: false,
    side: THREE.DoubleSide,
  }), []);
  const wire = useMemo(() => new THREE.MeshBasicMaterial({
    color: "#39c8ff", wireframe: true, transparent: true, opacity: 0.42,
    depthWrite: false,
  }), []);
  const dots = useMemo(() => new THREE.PointsMaterial({
    color: "#b3f7ff", size: 0.024, transparent: true, opacity: 0.8,
    sizeAttenuation: true, depthWrite: false, toneMapped: false,
  }), []);
  return (
    <group>
      <mesh geometry={geo} material={fill} />
      <mesh geometry={geo} material={wire} />
      <points geometry={geo} material={dots} />
      <MechanicalDetails accent={accent} material={fill} shaftMaterial={fill} />
      <Pinion geometry={pinionGeo} material={fill} accent={accent} wireframe />
      <ScanSweep accent={accent} reducedMotion={reducedMotion} />
    </group>
  );
}

function CadStage({ geo, pinionGeo, accent }) {
  const edgeGeometry = useMemo(() => new THREE.EdgesGeometry(geo, 15), [geo]);
  const body = useMemo(() => new THREE.MeshPhysicalMaterial({
    color: "#f0fbfc", metalness: 0.22, roughness: 0.18,
    clearcoat: 1, clearcoatRoughness: 0.12, transparent: true,
  }), []);
  const lines = useMemo(() => new THREE.LineBasicMaterial({
    color: "#73eaff", transparent: true, opacity: 0.88,
  }), []);
  return (
    <group>
      <mesh geometry={geo} material={body} castShadow receiveShadow />
      <lineSegments geometry={edgeGeometry} material={lines} />
      <MechanicalDetails accent={accent} material={body} />
      <Pinion geometry={pinionGeo} material={body} accent={accent} />
    </group>
  );
}

function PrintStage({ geo, pinionGeo, accent }) {
  const texture = useMemo(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 8;
    canvas.height = 128;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#d9e2e4";
    ctx.fillRect(0, 0, 8, 128);
    for (let y = 0; y < 128; y += 5) {
      ctx.fillStyle = y % 20 === 0 ? "#9db2ba" : "#c6d3d5";
      ctx.fillRect(0, y, 8, 1);
    }
    const map = new THREE.CanvasTexture(canvas);
    map.wrapS = map.wrapT = THREE.RepeatWrapping;
    map.repeat.set(2, 3);
    return map;
  }, []);
  const body = useMemo(() => new THREE.MeshPhysicalMaterial({
    map: texture, color: "#f2faf8", metalness: 0.16, roughness: 0.3,
    clearcoat: 0.72, transparent: true,
  }), [texture]);
  const bed = useMemo(() => new THREE.MeshPhysicalMaterial({
    color: "#182b36", metalness: 0.82, roughness: 0.24, clearcoat: 0.8,
  }), []);
  return (
    <group>
      <mesh geometry={geo} material={body} castShadow receiveShadow />
      <MechanicalDetails accent={accent} material={body} />
      <Pinion geometry={pinionGeo} material={body} accent={accent} />
      <mesh material={bed} position={[0, 0, -0.56]} rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[1.35, 1.4, 0.085, 96]} />
      </mesh>
      <mesh position={[0, 0, -0.51]}>
        <torusGeometry args={[1.39, 0.018, 10, 96]} />
        <GlowMaterial color={accent} opacity={0.85} />
      </mesh>
    </group>
  );
}

function FloatingRig({ reducedMotion, children }) {
  const ref = useRef();
  useFrame(({ clock }) => {
    if (!ref.current || reducedMotion) return;
    const t = clock.elapsedTime;
    ref.current.position.y = Math.sin(t * 0.72) * 0.055;
    ref.current.rotation.z = Math.sin(t * 0.22) * 0.018;
  });
  return <group ref={ref} scale={0.8}>{children}</group>;
}

function Scene({ stage, accent, brokenGeo, completeGeo, pinionGeo, reducedMotion }) {
  return (
    <>
      <fog attach="fog" args={["#F0F7FA", 7, 15]} />
      <StudioEnvironment />
      <ambientLight intensity={0.36} />
      <hemisphereLight args={["#f5ffff", "#405967", 0.75]} />
      <directionalLight position={[4.5, 6, 7]} intensity={2.5} color="#ffffff" castShadow />
      <directionalLight position={[-5, 1.8, 4]} intensity={1.8} color="#76e9ff" />
      <directionalLight position={[2, -4, -3]} intensity={1.3} color="#9daaff" />
      <pointLight position={[0, 0.2, 2.2]} intensity={1.25} color={accent} distance={6} />
      <Suspense fallback={null}>
        <HaloSystem accent={accent} reducedMotion={reducedMotion} />
        <FloatingRig reducedMotion={reducedMotion}>
          <group rotation={[0.48, 0.42, 0.04]}>
            <FadeGroup active={stage === 0}>
              <BrokenStage geo={brokenGeo} pinionGeo={pinionGeo} accent={accent} />
            </FadeGroup>
            <FadeGroup active={stage === 1}>
              <ScanStage geo={brokenGeo} pinionGeo={pinionGeo} accent={accent} reducedMotion={reducedMotion} />
            </FadeGroup>
            <FadeGroup active={stage === 2}>
              <CadStage geo={completeGeo} pinionGeo={pinionGeo} accent={accent} />
            </FadeGroup>
            <FadeGroup active={stage === 3}>
              <PrintStage geo={completeGeo} pinionGeo={pinionGeo} accent={accent} />
            </FadeGroup>
          </group>
        </FloatingRig>
        <mesh position={[0, 0, -0.31]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[1.15, 1.18, 0.12, 96]} />
          <meshPhysicalMaterial color="#dce8eb" metalness={0.7} roughness={0.3} transparent opacity={0.64} />
        </mesh>
        <mesh position={[0, 0, -0.235]}>
          <torusGeometry args={[1.16, 0.016, 12, 112]} />
          <GlowMaterial color={accent} opacity={0.6} />
        </mesh>
        <ContactShadows
          position={[0, -1.4, -0.3]}
          opacity={0.22}
          scale={6.5}
          blur={2.5}
          far={3.5}
          color="#24404f"
        />
      </Suspense>
      <OrbitControls
        makeDefault
        enablePan={false}
        minDistance={3.6}
        maxDistance={7}
        autoRotate={!reducedMotion}
        autoRotateSpeed={0.36}
        enableDamping
        dampingFactor={0.075}
        target={[0.35, 0, 0]}
      />
    </>
  );
}

function RepairedScene({ repairData, accent, reducedMotion }) {
  const stlGeo = useLoader(STLLoader, repairData.stl_url);
  
  useEffect(() => {
    stlGeo.center();
    stlGeo.computeVertexNormals();
  }, [stlGeo]);

  const edgeGeometry = useMemo(() => new THREE.EdgesGeometry(stlGeo, 15), [stlGeo]);
  
  const body = useMemo(() => new THREE.MeshPhysicalMaterial({
    color: "#f0fbfc", metalness: 0.22, roughness: 0.18,
    clearcoat: 1, clearcoatRoughness: 0.12, transparent: true,
  }), []);
  const lines = useMemo(() => new THREE.LineBasicMaterial({
    color: "#73eaff", transparent: true, opacity: 0.88,
  }), []);

  return (
    <>
      <fog attach="fog" args={["#F0F7FA", 7, 15]} />
      <StudioEnvironment />
      <ambientLight intensity={0.36} />
      <hemisphereLight args={["#f5ffff", "#405967", 0.75]} />
      <directionalLight position={[4.5, 6, 7]} intensity={2.5} color="#ffffff" castShadow />
      <directionalLight position={[-5, 1.8, 4]} intensity={1.8} color="#76e9ff" />
      <directionalLight position={[2, -4, -3]} intensity={1.3} color="#9daaff" />
      <pointLight position={[0, 0.2, 2.2]} intensity={1.25} color={accent} distance={6} />
      
      <HaloSystem accent={accent} reducedMotion={reducedMotion} />
      
      <FloatingRig reducedMotion={reducedMotion}>
        <mesh geometry={stlGeo} material={body} castShadow receiveShadow />
        <lineSegments geometry={edgeGeometry} material={lines} />
      </FloatingRig>
      
      <OrbitControls
        makeDefault
        enablePan={false}
        minDistance={3.6}
        maxDistance={12}
        autoRotate={!reducedMotion}
        autoRotateSpeed={0.36}
        enableDamping
        dampingFactor={0.075}
      />
    </>
  );
}

export default function Viewer3D({ stage, accent, repairData }) {
  const reduceMotion = useReducedMotion();
  const brokenGeo = useMemo(() => buildGearGeometry({ broken: true }), []);
  const completeGeo = useMemo(() => buildGearGeometry({ broken: false }), []);
  const pinionGeo = useMemo(() => buildGearGeometry({
    broken: false, teeth: 12, rootRadius: 0.39, tipRadius: 0.57,
    boreRadius: 0.105, boltRadius: 0.3, boltHoleRadius: 0.05,
  }), []);
  return (
    <div data-testid="hero-viewer-canvas" className="hero-3d-canvas absolute inset-0">
      <Suspense fallback={null}>
        <Canvas
          dpr={[1, 1.75]}
          camera={{ position: [3.05, 2.15, 4.25], fov: 35 }}
          gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
        >
          {repairData && repairData.stl_url ? (
            <RepairedScene
              repairData={repairData}
              accent={accent}
              reducedMotion={reduceMotion}
            />
          ) : (
            <Scene
              stage={stage}
              accent={accent}
              brokenGeo={brokenGeo}
              completeGeo={completeGeo}
              pinionGeo={pinionGeo}
              reducedMotion={reduceMotion}
            />
          )}
        </Canvas>
      </Suspense>
    </div>
  );
}
