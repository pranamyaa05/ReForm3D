import { motion } from "framer-motion";
import { ArrowUpRight } from "lucide-react";
import Logo from "./Logo";

const PRINTED_IMG = "/broken-mug.png";

export default function CTA({ onStartRepair, isUploading }) {
  return (
    <>
      <section id="cta" className="cta-section px-5 py-24 sm:px-8 md:py-36 lg:px-12">
        <div className="grid items-center gap-12 md:grid-cols-12">
          <motion.div
            initial={{ opacity: 0, y: 32 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.2 }}
            transition={{ duration: 0.7 }}
            className="md:col-span-7"
          >
            <span className="mono-label text-[11px] text-[#A2B9EE]">START AN ADAPTATION</span>
            <h2 className="mt-5 font-display text-[clamp(2.8rem,6.5vw,6rem)] font-black uppercase leading-[0.92] tracking-[-0.02em] text-[#0A0E12]">
              Inaccessible?
              <br />
              <span className="text-[#A2B9EE]">Send three photos.</span>
            </h2>
            <p className="mt-6 max-w-md text-[15px] leading-relaxed text-[#52667A]">
              Attach three angles of the object causing you trouble. We identify it, reason about your physical constraints, and
              return a print-ready, exact-fit ergonomic adapter — keeping another product out of the landfill.
            </p>
            <div className="mt-10 flex flex-wrap items-center gap-5">
              <button 
                onClick={onStartRepair}
                disabled={isUploading}
                className="group relative inline-flex cursor-pointer items-center gap-3 rounded-[4px] bg-[#A2B9EE] px-7 py-4 font-display text-sm font-extrabold uppercase tracking-wide text-[#0A0E12] transition-colors duration-300 hover:bg-[#0A0E12] hover:text-white"
              >
                {isUploading ? "Analysing Part..." : "Start adaptation"}
                {!isUploading && (
                  <ArrowUpRight
                    size={16}
                    className="transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:translate-x-0.5"
                  />
                )}
              </button>
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 32 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.2 }}
            transition={{ duration: 0.7, delay: 0.15 }}
            className="md:col-span-5"
            data-testid="cta-photo-card"
          >
            <div className="relative flex justify-center items-center">
              <img
                src={PRINTED_IMG}
                alt="Broken ceramic cup"
                className="max-h-[440px] w-full object-contain mix-blend-multiply"
              />
            </div>
          </motion.div>
        </div>
      </section>

      <footer className="border-t border-[#D8E4EE] px-5 py-8 sm:px-8 lg:px-12">
        <div className="flex flex-col items-center justify-between gap-4 md:flex-row">
          <div className="flex items-center gap-3">
            <Logo size={22} />
            <span className="font-display text-sm font-extrabold uppercase tracking-tight text-[#0A0E12]">
              ReForm
            </span>
          </div>
          <span className="mono-label text-[9px] text-[#7A8CA0]">REPAIR INSTEAD OF REPLACE</span>
          <span className="mono-label text-[9px] text-[#7A8CA0]">© 2025 REFORM</span>
        </div>
      </footer>
    </>
  );
}
