export const STAGES = [
  {
    id: "01",
    key: "broken",
    title: "INACCESSIBLE",
    card: "THE BARRIER",
    sub: "Standard twist cap — painful for users with osteoarthritis",
    accent: "#B4E4E6",
    eyebrow: "PART: PILL BOTTLE / TWIST CAP",
    blurb:
      "The bottle is fine, but the cap is a daily, painful barrier for 600 million people with osteoarthritis. The market's only option is throwing it away or buying expensive specialized equipment.",
    specs: [
      ["BARRIER", "GRIP / ROTATE"],
      ["SDG FOCUS", "SDG 10 - INEQUALITIES"],
      ["STATUS", "UNAUSABLE"],
    ],
    status: "AWAITING SCAN — 3 PHOTOS NEEDED",
  },
  {
    id: "02",
    key: "scan",
    title: "SCANNED",
    card: "PHOTO SCAN",
    sub: "3 photos map the cap's exact geometry",
    accent: "#C9C1F1",
    eyebrow: "STAGE 02 / AI IDENTIFICATION",
    blurb:
      "No scanner required. Three phone photos are enough. Our vision model identifies the object, maps its dimensions, and recognizes the 'GRIP and ROTATE' functional requirement.",
    specs: [
      ["TOLERANCE", "±0.12 MM · INFERRED"],
      ["GEOMETRY ENGINE", "REFORM VISION AI"],
      ["INTERFACE", "PHYSICAL ADAPTATION"],
    ],
    status: "PART IDENTIFIED — FUNCTION INFERRED",
  },
  {
    id: "03",
    key: "cad",
    title: "ADAPTED",
    card: "CUSTOM CAD",
    sub: "Generative design creates an exact-fit grip",
    accent: "#E2C3F6",
    eyebrow: "STAGE 03 / PROBLEM REASONING",
    blurb:
      "The AI connects the dots: Bottle + GRIP + limited mobility = insufficient torque. It generates a parametric, exact-fit ergonomic wing adapter designed to slip over the existing cap.",
    specs: [
      ["SOLUTION", "ERGONOMIC WING GRIP"],
      ["MATERIAL", "15 GRAMS PLA"],
      ["ECONOMICS", "LESS THAN ₹20 COST"],
    ],
    status: "ADAPTIVE CAD GENERATED",
  },
  {
    id: "04",
    key: "print",
    title: "UPGRADED",
    card: "PRINTED FIX",
    sub: "Slip-on grip — usability instantly restored",
    accent: "#B8E3D1",
    eyebrow: "STAGE 04 / ACCESSIBILITY RESTORED",
    blurb:
      "The custom grip bolts straight on. Instead of replacing the existing product, we upgraded it. We adapt the world to the user, keeping another product out of the landfill.",
    specs: [
      ["IMPACT", "SDG 12 - RESPONSIBLE CONSUMPTION"],
      ["PRODUCTION", "DISTRIBUTED FDM PRINT"],
      ["RESULT", "100% USABILITY RESTORED"],
    ],
    status: "FITTED — ACCESSIBILITY COMPLETE",
  },
];
