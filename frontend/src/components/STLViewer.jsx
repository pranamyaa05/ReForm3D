import { useEffect } from "react";
import { Canvas, useLoader } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader";

export default function STLViewer({ url }) {
  return (
    <Canvas camera={{ position: [0, -45, 35], fov: 45 }}>
      <color attach="background" args={["#0A0E12"]} />
      <ambientLight intensity={0.85} />
      <directionalLight position={[60, 80, 100]} intensity={1.3} color="#A2B9EE" />
      <directionalLight position={[-60, -50, -40]} intensity={0.7} color="#B4E4E6" />
      <Model url={url} />
      <OrbitControls autoRotate enableDamping />
    </Canvas>
  );
}

function Model({ url }) {
  const geom = useLoader(STLLoader, url);

  useEffect(() => {
    geom.center();
    geom.computeVertexNormals();
  }, [geom]);

  return (
    <mesh geometry={geom}>
      <meshPhysicalMaterial color="#A2B9EE" metalness={0.3} roughness={0.28} clearcoat={0.6} />
    </mesh>
  );
}
