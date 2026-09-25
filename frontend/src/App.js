import React, { useEffect, useState, Component } from "react";
import { MotionConfig } from "framer-motion";
import Lenis from "lenis";
import Nav from "./components/Nav";
import Hero, { BgRings } from "./components/Hero";
import Marquee from "./components/Marquee";
import Pipeline from "./components/Pipeline";
import CTA from "./components/CTA";
import PhotoEntryPage from "./components/PhotoEntryPage";
import "./App.css";

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed) {
      return (
        <div className="p-10 font-mono text-sm text-[#52667A]">
          Something broke in this section.
        </div>
      );
    }
    return this.props.children;
  }
}

function AmbientMesh() {
  return (
    <div className="fixed inset-0 pointer-events-none overflow-hidden z-0" aria-hidden="true">
      <div className="absolute top-[-10%] left-[-10%] h-[70vw] w-[70vw] rounded-full bg-[#A2B9EE] opacity-[0.15] blur-[140px] mix-blend-multiply" />
      <div className="absolute top-[40%] right-[-10%] h-[60vw] w-[60vw] rounded-full bg-[#E2C3F6] opacity-[0.15] blur-[160px] mix-blend-multiply" />
      <div className="absolute bottom-[-20%] left-[20%] h-[80vw] w-[80vw] rounded-full bg-[#B8E3D1] opacity-[0.15] blur-[150px] mix-blend-multiply" />
    </div>
  );
}

export default function App() {
  const [showWorkflow, setShowWorkflow] = useState(false);
  const [repairData, setRepairData] = useState(null);
  const [isUploading, setIsUploading] = useState(false);

  useEffect(() => {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) return undefined;
    const lenis = new Lenis({ lerp: 0.09 });
    window.__lenis = lenis;
    let id;
    const raf = (t) => {
      lenis.raf(t);
      id = requestAnimationFrame(raf);
    };
    id = requestAnimationFrame(raf);
    return () => {
      cancelAnimationFrame(id);
      lenis.destroy();
      window.__lenis = null;
    };
  }, []);

  return (
    <MotionConfig reducedMotion="user">
      <ErrorBoundary>
        <div className="relative bg-[#FCF9F2] min-h-screen">
          <AmbientMesh />
          <Nav />
          {showWorkflow ? (
            <section className="hero-section relative flex min-h-[100svh] flex-col overflow-hidden pt-28 pb-12">
              <BgRings />
              <div className="relative z-10 max-w-5xl mx-auto px-4 w-full">
                <div className="mb-6">
                  <button 
                    onClick={() => setShowWorkflow(false)}
                    className="group flex items-center gap-2 font-display text-sm font-extrabold uppercase tracking-wide text-[#0A0E12] transition-colors hover:text-[#A2B9EE]"
                  >
                    <span className="transition-transform group-hover:-translate-x-1">&larr;</span> BACK TO HOME
                  </button>
                </div>
                <PhotoEntryPage />
              </div>
            </section>
          ) : (
            <>
              <Hero repairData={repairData} />
              <Marquee />
              <Pipeline />
              {/* Modify CTA to just trigger showWorkflow instead of uploading inline */}
              <CTA onStartRepair={() => {
                setShowWorkflow(true);
                window.scrollTo({ top: 0, behavior: "smooth" });
              }} isUploading={false} />
            </>
          )}
        </div>
      </ErrorBoundary>
    </MotionConfig>
  );
}
