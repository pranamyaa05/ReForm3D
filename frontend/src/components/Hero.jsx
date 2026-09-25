import { useState } from "react";
import { motion, AnimatePresence, useScroll, useTransform } from "framer-motion";
import { ArrowDown, ArrowLeft, ArrowRight } from "lucide-react";
import Viewer3D from "./Viewer3D";
import { STAGES } from "../lib/stages";
import { scrollToId } from "../lib/scroll";

const ease = [0.16, 1, 0.3, 1];

export function BgRings() {
  const { scrollYProgress } = useScroll();
  const y = useTransform(scrollYProgress, [0, 1], [0, 140]);
  return (
    <motion.div
      style={{ y }}
      className="pointer-events-none absolute inset-0 overflow-hidden"
      aria-hidden="true"
    >
      <div className="absolute right-[-12%] top-1/2 hidden -translate-y-1/2 md:block">
        <svg className="animate-spin-slower h-[880px] w-[880px]" viewBox="0 0 880 880" fill="none">
          <circle cx="440" cy="440" r="130" stroke="#B4E4E6" strokeOpacity="0.4" strokeWidth="2" />
          <circle cx="440" cy="440" r="230" stroke="#C9C1F1" strokeOpacity="0.3" strokeWidth="2" />
          <circle cx="440" cy="440" r="330" stroke="#B8E3D1" strokeOpacity="0.4" strokeDasharray="4 12" strokeWidth="2" />
          <circle cx="440" cy="440" r="428" stroke="#A2B9EE" strokeOpacity="0.3" strokeWidth="1.5" />
          <path d="M440 12v60M440 808v60M12 440h60M808 440h60" stroke="#B4E4E6" strokeOpacity="0.4" strokeWidth="2" />
        </svg>
      </div>
    </motion.div>
  );
}

function StageCarousel({ stage, setStage, prev, next }) {
  return (
    <div className="flex items-stretch">
      <button
        data-testid="stage-prev"
        onClick={prev}
        aria-label="Previous stage"
        className="hidden w-14 items-center justify-center border-r border-[#D8E4EE] text-[#0A0E12] transition-colors hover:bg-white md:flex"
      >
        <ArrowLeft size={16} />
      </button>
      <div className="grid flex-1 grid-cols-2 md:grid-cols-4" role="tablist" aria-label="Repair stages">
        {STAGES.map((st, i) => {
          const active = i === stage;
          return (
            <button
              key={st.id}
              data-testid={`stage-card-${st.id}`}
              onClick={() => setStage(i)}
              role="tab"
              aria-selected={active}
              className={`stage-choice relative overflow-hidden px-4 py-3 text-left transition-colors md:py-4 ${
                active ? "bg-white" : "bg-transparent hover:bg-white/60"
              } ${i >= 2 ? "border-t border-[#D8E4EE] md:border-t-0" : ""} ${
                i > 0 ? "border-l border-[#D8E4EE]" : ""
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="mono-label text-[9px] text-[#7A8CA0]">{st.id}</span>
                {active && <span className="stage-bg h-1.5 w-1.5 rounded-full" />}
              </div>
              <div className="mt-1 font-display text-sm font-extrabold uppercase tracking-tight text-[#0A0E12] md:text-base">
                {st.card}
              </div>
              <div className="mt-0.5 hidden text-[11px] leading-snug text-[#7A8CA0] md:block">
                {st.sub}
              </div>
              {active && <span className="stage-bg absolute left-0 top-0 h-full w-[3px]" />}
            </button>
          );
        })}
      </div>
      <button
        data-testid="stage-next"
        onClick={next}
        className="hidden items-center gap-2 border-l border-[#D8E4EE] px-6 transition-colors hover:bg-white md:flex"
      >
        <span className="mono-label text-[10px] text-[#0A0E12]">NEXT</span>
        <ArrowRight size={14} className="stage-text" />
      </button>
    </div>
  );
}

export default function Hero({ repairData }) {
  const [stage, setStage] = useState(0);
  const s = STAGES[stage];
  const prev = () => setStage((stage + STAGES.length - 1) % STAGES.length);
  const next = () => setStage((stage + 1) % STAGES.length);

  return (
    <section
      id="top"
      className="hero-section vgrid relative flex min-h-[100svh] flex-col overflow-hidden"
      style={{ "--stage": s.accent }}
    >
      <BgRings />

      <div className="hero-layout relative z-10 mx-auto grid w-full max-w-[1440px] flex-1 lg:grid-cols-12">
        <div className="hero-copy relative z-10 px-5 pt-28 sm:px-8 lg:col-span-5 lg:pt-36 lg:pl-12">
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease, delay: 0.1 }}
            className="flex items-center gap-3"
          >
            <span className="stage-bg h-px w-10" />
            <span className="mono-label text-[11px] text-[#405263]">
              {repairData ? repairData.diagnosis.object_identified : s.eyebrow}
            </span>
          </motion.div>

          <div className="mt-4 overflow-hidden">
            <AnimatePresence mode="wait">
              <motion.h1
                key={repairData ? "repaired" : s.key}
                data-testid="hero-headline"
                initial={{ y: "112%" }}
                animate={{ y: "0%" }}
                exit={{ y: "-112%" }}
                transition={{ duration: 0.55, ease }}
                className="font-display font-black uppercase leading-[0.9] tracking-[-0.02em] text-[#0A0E12]"
              >
                {repairData ? repairData.diagnosis.suggested_template.replace(/_/g, " ") : s.title}
              </motion.h1>
            </AnimatePresence>
          </div>

          <AnimatePresence mode="wait">
            <motion.div
              key={repairData ? "repaired" : s.key}
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.4, ease }}
            >
              <p
                className="mt-5 max-w-md text-[15px] leading-relaxed text-[#405263]"
                data-testid="hero-blurb"
              >
                {repairData ? repairData.diagnosis.failure_diagnosis : s.blurb}
              </p>

              <div
                className="mt-8 grid grid-cols-3 divide-x divide-[#D8E4EE] border-y border-[#D8E4EE]"
                data-testid="hero-spec-row"
              >
                {repairData ? repairData.diagnosis.measurements.slice(0, 3).map((m, i) => (
                  <div key={m.feature_name} data-testid={`spec-col-${i}`} className="py-4 pl-3 pr-3 first:pl-0">
                    <div className="mono-label text-[9px] text-[#7A8CA0] uppercase">{m.feature_name.replace(/_/g, " ")}</div>
                    <div className="mt-1.5 font-mono text-[13px] font-semibold tracking-tight text-[#0A0E12]">
                      {m.estimated_value_mm} MM
                    </div>
                  </div>
                )) : s.specs.map(([k, v], i) => (
                  <div key={k} data-testid={`spec-col-${i}`} className="py-4 pl-3 pr-3 first:pl-0">
                    <div className="mono-label text-[9px] text-[#7A8CA0]">{k}</div>
                    <div className="mt-1.5 font-mono text-[13px] font-semibold tracking-tight text-[#0A0E12]">
                      {v}
                    </div>
                  </div>
                ))}
              </div>

            </motion.div>
          </AnimatePresence>

          <motion.button
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.9 }}
            onClick={() => scrollToId("pipeline")}
            data-testid="hero-scroll-hint"
            className="mono-label mt-8 hidden items-center gap-2 text-[10px] text-[#52667A] transition-colors hover:text-[#0A0E12] lg:inline-flex"
          >
            SEE THE PIPELINE <ArrowDown size={12} />
          </motion.button>
        </div>

        <div className="hero-visual relative min-h-[48vh] lg:col-span-7 lg:min-h-0">
          <Viewer3D stage={stage} accent={s.accent} repairData={repairData} />
          <div className="viewer-hud viewer-hud-top" aria-hidden="true">
            <span className="viewer-hud-live"><span /> LIVE MODEL</span>
          </div>
          <div className="viewer-hud viewer-hud-bottom" aria-hidden="true">
            <span className="viewer-crosshair">＋</span>
            <span>INTERACTIVE 3D</span>
            <span className="viewer-hud-separator" />
            <span>DRAG TO ROTATE</span>
            <span className="viewer-hud-separator" />
            <span>SCROLL TO ZOOM</span>
          </div>
          <div className="pointer-events-none absolute right-5 top-1/2 hidden -translate-y-1/2 flex-col items-center gap-2 md:flex">
            <span className="font-mono text-sm font-semibold text-[#0A0E12]" data-testid="frame-index-current">
              0{stage + 1}
            </span>
            <span className="h-10 w-px bg-[#0A0E12]/20" />
            <span className="font-mono text-sm text-[#7A8CA0]">04</span>
          </div>
        </div>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease, delay: 0.5 }}
        className="stage-dock relative z-10 border-t border-[#D8E4EE] bg-[#F0F7FA]/85 backdrop-blur-md"
      >
        <StageCarousel stage={stage} setStage={setStage} prev={prev} next={next} />
      </motion.div>
    </section>
  );
}
