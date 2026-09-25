import { motion } from "framer-motion";
import { Camera, BrainCircuit, Activity, Printer, ArrowUpRight } from "lucide-react";

const STEPS = [
  {
    n: "01",
    icon: Camera,
    t: "PHOTOGRAPH",
    d: "Snap three photos of the inaccessible object. No scanner, no studio — a phone is enough to map the barrier.",
  },
  {
    n: "02",
    icon: BrainCircuit,
    t: "IDENTIFY",
    d: "Our Vision-Language Model identifies the object (e.g., a bottle cap) and maps it to a physical interaction vocabulary like 'GRIP and ROTATE'.",
  },
  {
    n: "03",
    icon: Activity,
    t: "REASON & GENERATE",
    d: "The AI connects the dots (Bottle + GRIP + limited mobility) and generates a parametric, exact-fit ergonomic adapter.",
  },
  {
    n: "04",
    icon: Printer,
    t: "PRINT & FIT",
    d: "We print the custom intervention using 15g of filament. It slips on perfectly. You didn't buy a new product, you upgraded it.",
  },
];

export default function Pipeline() {
  return (
    <section id="pipeline" className="pipeline-section relative px-5 py-24 sm:px-8 md:py-32 lg:px-12">
      <div className="mb-14 flex flex-col gap-6 md:mb-20 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="flex items-center gap-3">
            <span className="h-px w-10 bg-[#AEDDF0]" />
            <span className="mono-label text-[11px] text-[#AEDDF0]">WORKFLOW</span>
          </div>
          <h2 className="mt-4 font-display text-4xl font-black uppercase leading-[0.95] tracking-tight text-[#0A0E12] sm:text-5xl lg:text-6xl">
            From barrier to
            <br />
            accessibility
          </h2>
        </div>
        <p className="max-w-sm text-[15px] leading-relaxed text-[#52667A]">
          Four steps between a frustrating object and a customized, printable intervention.
        </p>
      </div>

      <div className="border-b border-[#D8E4EE]">
        {STEPS.map((st, i) => {
          const Icon = st.icon;
          return (
            <motion.div
              key={st.n}
              initial={{ opacity: 0, y: 24 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={{ duration: 0.6, delay: i * 0.05 }}
              data-testid={`pipeline-step-${st.n}`}
              className="process-row group flex flex-col gap-3 border-t border-[#D8E4EE] py-7 transition-all duration-300 hover:bg-white/70 md:flex-row md:items-center md:gap-10 md:py-9 md:pl-4 md:pr-8 md:hover:pl-8"
            >
              <span className="font-mono text-xs text-[#7A8CA0] md:w-12">{st.n}</span>
              <div className="flex flex-1 items-center gap-4">
                <Icon
                  size={20}
                  className="shrink-0 text-[#A2B9EE] transition-transform duration-300 group-hover:scale-110"
                />
                <h3 className="font-display text-2xl font-extrabold uppercase tracking-tight text-[#0A0E12] md:text-4xl">
                  {st.t}
                </h3>
              </div>
              <p className="max-w-md text-sm leading-relaxed text-[#52667A] md:w-[380px]">{st.d}</p>
              <ArrowUpRight
                size={18}
                className="hidden text-[#7A8CA0] opacity-0 transition-all duration-300 group-hover:translate-x-1 group-hover:opacity-100 md:block"
              />
            </motion.div>
          );
        })}
      </div>
    </section>
  );
}
