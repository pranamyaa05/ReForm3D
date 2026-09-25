import { Pill, Settings, Archive, Droplet, DoorOpen, Utensils, Key, Lightbulb, Scissors, Pen, Coffee } from "lucide-react";

const ITEMS = [
  { id: "pill", Icon: Pill },
  { id: "settings", Icon: Settings },
  { id: "archive", Icon: Archive },
  { id: "droplet", Icon: Droplet },
  { id: "door", Icon: DoorOpen },
  { id: "utensils", Icon: Utensils },
  { id: "key", Icon: Key },
  { id: "lightbulb", Icon: Lightbulb },
  { id: "scissors", Icon: Scissors },
  { id: "pen", Icon: Pen },
  { id: "coffee", Icon: Coffee },
];

export default function Marquee() {
  return (
    <div data-testid="marquee" className="marquee overflow-hidden border-y border-[#0A0E12] bg-[#0A0E12] py-5">
      <div className="marquee-track">
        {[0, 1].map((copy) => (
          <div key={copy} aria-hidden={copy === 1} className="flex shrink-0 items-center">
            {ITEMS.map(({ id, Icon }) => (
              <span key={id} className="flex items-center px-10">
                <Icon size={40} className="text-[#EEF3F6] opacity-80" />
                <span className="font-mono text-xl text-[#AEDDF0] ml-10 opacity-50">//</span>
              </span>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
