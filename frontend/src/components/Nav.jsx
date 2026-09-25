import { useState } from "react";
import { ArrowUpRight, Menu, X } from "lucide-react";
import Logo from "./Logo";
import { scrollToId } from "../lib/scroll";

const LINKS = [];

export default function Nav() {
  const [open, setOpen] = useState(false);
  const goTo = (id) => {
    setOpen(false);
    scrollToId(id);
  };

  return (
    <header className="site-header fixed inset-x-0 top-0 z-50">
      <div className="site-header-inner mx-auto flex h-[72px] items-center justify-between px-5 sm:px-8 lg:px-12">
        <a href="#top" onClick={(event) => { event.preventDefault(); goTo("top"); }} className="brand-lockup" aria-label="ReForm home" data-testid="nav-brand">
          <Logo size={30} />
          <span className="brand-name font-display">ReForm</span>
          <span className="brand-divider" />
          <span className="brand-descriptor mono-label">Repair intelligence</span>
        </a>

        <nav id="mobile-navigation" className={`site-nav ${open ? "is-open" : ""}`} aria-label="Main navigation">
          {LINKS.map((link) => (
            <a key={link.id} href={`#${link.id}`} onClick={(event) => { event.preventDefault(); goTo(link.id); }}>
              {link.label}
            </a>
          ))}
          <button data-testid="nav-cta" onClick={() => goTo("cta")} className="nav-cta">
            Start an adaptation <ArrowUpRight size={15} aria-hidden="true" />
          </button>
        </nav>

        <button
          type="button"
          className="nav-menu-toggle"
          aria-label={open ? "Close navigation menu" : "Open navigation menu"}
          aria-expanded={open}
          aria-controls="mobile-navigation"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>
    </header>
  );
}
