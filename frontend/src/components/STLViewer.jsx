import { useEffect } from 'react';
import { Canvas, useLoader } from '@react-three/fiber';
import { OrbitControls, Stage } from '@react-three/drei';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader';

export default function STLViewer({ url }: { url: string }) {
  return (
    <Canvas camera={{ position: [0, 0, 5], fov: 45 }}>
      <color attach="background" args={['#111827']} />
      <ambientLight intensity={0.5} />
      <directionalLight position={[10, 10, 10]} intensity={1} />
      <Model url={url} />
      <OrbitControls autoRotate />
    </Canvas>
  );
}

function Model({ url }: { url: string }) {
  const geom = useLoader(STLLoader, url);
  
  useEffect(() => {
    geom.center();
    geom.computeVertexNormals();
  }, [geom]);

  return (
    <mesh geometry={geom}>
      <meshStandardMaterial color="#3b82f6" metalness={0.5} roughness={0.5} />
    </mesh>
  );
}
