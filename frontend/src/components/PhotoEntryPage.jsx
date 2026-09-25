import { useState, useEffect } from "react";
import { Camera, Image as ImageIcon, CheckCircle2, ChevronRight, Download, Box, Activity } from "lucide-react";
import STLViewer from "./STLViewer";

const API_BASE = process.env.REACT_APP_BACKEND_URL || "http://127.0.0.1:8000";

const SLOT_MAP = {
  front: { kind: "straight_on", label: "Front View" },
  side: { kind: "angled", label: "Side / Angled View" },
  back: { kind: "mating_surface", label: "Close-Up + Scale Object" },
};

const FRIENDLY_LABELS = {
  bore_diameter_mm: "Inner Bore Diameter",
  wall_thickness_mm: "Wall Thickness",
  height_mm: "Collar Height",
  clip_width_mm: "Inner Clip Width",
  clip_depth_mm: "Clip Depth",
  flex_thickness_mm: "Flex Arm Thickness",
  cap_diameter_mm: "Knob / Cap Diameter",
  lever_length_mm: "Torque Lever Length",
  cap_height_mm: "Cap Socket Height",
  base_diameter_mm: "Base Knob Diameter",
  wing_span_mm: "Total Wing Span",
  base_height_mm: "Adapter Hub Height",
};

export default function PhotoEntryPage() {
  const [step, setStep] = useState(1);
  const [sessionId, setSessionId] = useState(null);
  const [referenceType, setReferenceType] = useState("coin");
  const [photos, setPhotos] = useState({ front: null, side: null, back: null });
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isBuilding, setIsBuilding] = useState(false);
  const [diagnosis, setDiagnosis] = useState(null);
  const [template, setTemplate] = useState("friction_fit_collar");
  const [measurements, setMeasurements] = useState([]);
  const [clearanceMm, setClearanceMm] = useState(0.2);
  const [confirmed, setConfirmed] = useState(true);
  const [cadResult, setCadResult] = useState(null);
  const [errorMsg, setErrorMsg] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/api/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reference_type: "coin" }),
    })
      .then((r) => r.json())
      .then((d) => setSessionId(d.session_id))
      .catch(() => {});
  }, []);

  const handlePhotoUpload = async (view, e) => {
    const file = e.target.files?.[0];
    if (!file || !sessionId) return;
    setErrorMsg("");

    const url = URL.createObjectURL(file);
    setPhotos((prev) => ({ ...prev, [view]: url }));

    const fd = new FormData();
    fd.append("session_id", sessionId);
    fd.append("shot_kind", SLOT_MAP[view].kind);
    fd.append("file", file);
    fd.append("reference_type", referenceType);
    fd.append("bbox", JSON.stringify({ x_min: 0.16, y_min: 0.16, x_max: 0.46, y_max: 0.46 }));
    fd.append("overridden", "true");

    await fetch(`${API_BASE}/api/capture`, { method: "POST", body: fd });
  };

  const allPhotosUploaded = photos.front && photos.side && photos.back;

  const handleAnalyze = async () => {
    setErrorMsg("");
    setStep(2);
    setIsAnalyzing(true);
    try {
      const res = await fetch(`${API_BASE}/api/diagnose`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, run_enhancement: true }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail?.message || data.detail || "Analysis failed");
      const diag = data.diagnosis;
      setDiagnosis(diag);
      setTemplate(
        diag.suggested_template && diag.suggested_template !== "other"
          ? diag.suggested_template
          : "friction_fit_collar"
      );
      setMeasurements(diag.measurements || []);
    } catch (e) {
      setErrorMsg(e.message || "Failed to analyze photos.");
      setStep(1);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleGenerateCad = async () => {
    if (!confirmed) {
      setErrorMsg("Please check the confirmation box before generating your 3D model.");
      return;
    }
    setErrorMsg("");
    setIsBuilding(true);
    try {
      const res = await fetch(`${API_BASE}/api/generate-cad`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template,
          measurements,
          clearance_mm: parseFloat(clearanceMm) || 0.2,
          user_confirmed: true,
          session_id: sessionId,
          object_identified: diagnosis?.object_identified || "Custom Repair Part",
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error_message || data.message || "Failed to generate 3D model.");
      }
      setCadResult(data);
      setStep(3);
    } catch (e) {
      setErrorMsg(e.message);
    } finally {
      setIsBuilding(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto">
      {/* Stepper */}
      <div className="mb-8">
        <div className="flex items-center justify-between">
          {[
            { num: 1, title: "Capture" },
            { num: 2, title: "Review & Customize" },
            { num: 3, title: "3D Result" },
          ].map((s, idx) => (
            <div key={s.num} className="flex items-center flex-1">
              <div
                className={`flex items-center justify-center w-10 h-10 rounded-full border-2 ${
                  step >= s.num
                    ? "border-[#A2B9EE] bg-[#A2B9EE] text-[#0A0E12]"
                    : "border-[#D8E4EE] text-[#7A8CA0]"
                }`}
              >
                {step > s.num ? (
                  <CheckCircle2 className="w-6 h-6" />
                ) : (
                  <span className="font-mono text-sm font-semibold">{s.num}</span>
                )}
              </div>
              <span className={`ml-3 font-medium ${step >= s.num ? "text-gray-900" : "text-gray-400"}`}>
                {s.title}
              </span>
              {idx < 2 && <div className="flex-1 mx-4 h-0.5 bg-gray-200" />}
            </div>
          ))}
        </div>
      </div>

      {errorMsg && (
        <div className="mb-4 p-4 rounded-lg bg-red-50 border border-red-200 text-sm text-red-800">
          {errorMsg}
        </div>
      )}

      <div className="bg-[#F0F7FA]/85 backdrop-blur-md rounded-xl border border-[#D8E4EE] overflow-hidden">
        {step === 1 && (
          <div className="p-8">
            <h2 className="font-display text-2xl font-black uppercase tracking-tight text-[#0A0E12] mb-2">
              Step 1: Capture Your Object
            </h2>
            <p className="text-[#52667A] mb-6 leading-relaxed">
              Upload or take three clear photos of the part you want to repair, with a scale reference placed flat beside it.
            </p>

            {/* Scale Reference Selector */}
            <div className="mb-6">
              <span className="mono-label text-[10px] text-[#7A8CA0] uppercase block mb-2">
                Scale Reference Object
              </span>
              <div className="grid grid-cols-3 gap-3">
                {[
                  { id: "coin", label: "Coin (24.26 mm)" },
                  { id: "credit_card", label: "Bank Card (85.6 mm)" },
                  { id: "ruler", label: "Ruler (100 mm)" },
                ].map((ref) => (
                  <button
                    key={ref.id}
                    type="button"
                    onClick={() => setReferenceType(ref.id)}
                    className={`p-3 rounded-lg border text-left text-xs font-semibold transition-colors ${
                      referenceType === ref.id
                        ? "border-[#A2B9EE] bg-white text-[#0A0E12]"
                        : "border-[#D8E4EE] bg-white/50 text-[#52667A]"
                    }`}
                  >
                    {ref.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {["front", "side", "back"].map((view) => (
                <div key={view} className="flex flex-col">
                  <span className="mono-label text-[10px] text-[#7A8CA0] uppercase mb-2">
                    {SLOT_MAP[view].label}
                  </span>
                  <div className="relative border-2 border-dashed border-[#D8E4EE] rounded-lg bg-white/50 flex flex-col items-center justify-center aspect-[3/4] hover:bg-white transition-colors group cursor-pointer">
                    {photos[view] ? (
                      <img src={photos[view]} alt={view} className="w-full h-full object-cover rounded-lg" />
                    ) : (
                      <div className="text-center p-4">
                        <Camera className="mx-auto h-12 w-12 text-gray-400 mb-2 group-hover:text-blue-500 transition-colors" />
                        <span className="text-sm text-gray-500">Choose or take photo</span>
                      </div>
                    )}
                    <input
                      type="file"
                      accept="image/*"
                      onChange={(e) => handlePhotoUpload(view, e)}
                      className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                    />
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-8 flex justify-end">
              <button
                onClick={handleAnalyze}
                disabled={!allPhotosUploaded}
                className={`group relative inline-flex cursor-pointer items-center gap-3 rounded-[4px] px-7 py-4 font-display text-sm font-extrabold uppercase tracking-wide transition-colors duration-300 ${
                  allPhotosUploaded
                    ? "bg-[#A2B9EE] text-[#0A0E12] hover:bg-[#0A0E12] hover:text-white"
                    : "bg-[#D8E4EE] cursor-not-allowed text-[#7A8CA0]"
                }`}
              >
                Analyze &amp; Measure <ChevronRight className="ml-2 w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {step === 2 && isAnalyzing && (
          <div className="p-8 text-center">
            <h2 className="font-display text-2xl font-black uppercase tracking-tight text-[#0A0E12] mb-4">
              Analyzing Your Photos...
            </h2>
            <p className="text-[#52667A] mb-12 max-w-2xl mx-auto leading-relaxed">
              Isolating your object, correcting lighting, and calibrating millimeter measurements.
            </p>
            <div className="flex justify-center items-center space-x-12 mb-8">
              <div className="flex flex-col items-center">
                <div className="w-24 h-24 rounded-full bg-[#E5EEFF] flex items-center justify-center animate-pulse mb-4">
                  <ImageIcon className="w-10 h-10 text-[#A2B9EE]" />
                </div>
                <span className="mono-label text-[10px] text-[#0A0E12]">ISOLATING OBJECT</span>
              </div>
              <Activity className="w-8 h-8 text-[#D8E4EE]" />
              <div className="flex flex-col items-center">
                <div className="w-24 h-24 rounded-full bg-[#B4E4E6]/20 flex items-center justify-center animate-pulse mb-4">
                  <Box className="w-10 h-10 text-[#B4E4E6]" />
                </div>
                <span className="mono-label text-[10px] text-[#0A0E12]">EXTRACTING DIMENSIONS</span>
              </div>
            </div>
          </div>
        )}

        {step === 2 && !isAnalyzing && (
          <div className="p-8">
            <h2 className="font-display text-2xl font-black uppercase tracking-tight text-[#0A0E12] mb-2">
              Step 2: Review &amp; Customize Measurements
            </h2>
            <p className="text-[#52667A] mb-6">
              {diagnosis?.object_identified} — {diagnosis?.failure_diagnosis}
            </p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
              <div className="bg-white/80 p-4 rounded-lg border border-[#D8E4EE]">
                <label className="mono-label text-[10px] text-[#7A8CA0] uppercase block mb-2">
                  Replacement Attachment Style
                </label>
                <select
                  value={template}
                  onChange={(e) => setTemplate(e.target.value)}
                  className="w-full p-2.5 rounded border border-[#D8E4EE] bg-white font-semibold text-sm mb-4"
                >
                  <option value="friction_fit_collar">Friction-Fit Collar Sleeve</option>
                  <option value="snap_clip_bracket">Flexible Snap-Clip Bracket</option>
                  <option value="lever_cap">Slip-On Torque Lever Cap</option>
                  <option value="wing_adapter">Dual-Wing Twist Adapter</option>
                </select>

                <label className="mono-label text-[10px] text-[#7A8CA0] uppercase block mb-2">
                  Fit Tolerance / Clearance (mm)
                </label>
                <input
                  type="number"
                  step="0.05"
                  value={clearanceMm}
                  onChange={(e) => setClearanceMm(e.target.value)}
                  className="w-full p-2.5 rounded border border-[#D8E4EE] bg-white font-semibold text-sm"
                />
              </div>

              <div className="bg-white/80 p-4 rounded-lg border border-[#D8E4EE] space-y-3">
                <span className="mono-label text-[10px] text-[#7A8CA0] uppercase block">
                  Calibrated Dimensions (mm)
                </span>
                {measurements.map((m, idx) => (
                  <div key={m.feature_name} className="flex items-center justify-between gap-3">
                    <span className="text-sm font-semibold text-[#0A0E12]">
                      {FRIENDLY_LABELS[m.feature_name] || m.feature_name}
                    </span>
                    <input
                      type="number"
                      step="0.1"
                      value={m.estimated_value_mm}
                      onChange={(e) => {
                        const next = [...measurements];
                        next[idx] = { ...m, estimated_value_mm: parseFloat(e.target.value) || 0 };
                        setMeasurements(next);
                      }}
                      className="w-28 p-2 rounded border border-[#D8E4EE] bg-white font-mono text-sm font-semibold"
                    />
                  </div>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-[#D8E4EE]">
              <label className="flex items-center gap-2 text-sm font-semibold text-[#0A0E12] cursor-pointer">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                I have verified these dimensions
              </label>

              <button
                onClick={handleGenerateCad}
                disabled={isBuilding}
                className="inline-flex items-center gap-2 rounded-[4px] px-7 py-3.5 font-display text-sm font-extrabold uppercase tracking-wide bg-[#A2B9EE] text-[#0A0E12] hover:bg-[#0A0E12] hover:text-white transition-colors"
              >
                {isBuilding ? "Generating 3D Solid..." : "Generate 3D Model"}
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="p-8">
            <h2 className="font-display text-2xl font-black uppercase tracking-tight text-[#0A0E12] mb-4">
              Step 3: 3D Model Generated
            </h2>
            <p className="text-[#52667A] mb-8 leading-relaxed">
              Your custom replacement part has been generated and verified watertight. Preview the model below and download the STL or STEP file.
            </p>

            <div className="aspect-video bg-[#0A0E12] rounded-xl mb-8 flex items-center justify-center relative overflow-hidden shadow-[inset_0_2px_20px_rgba(0,0,0,0.5)]">
              {cadResult?.stl_url ? (
                <STLViewer url={`${API_BASE}${cadResult.stl_url}`} />
              ) : (
                <div className="relative z-10 flex flex-col items-center">
                  <Box className="w-16 h-16 text-[#A2B9EE] mb-4 animate-bounce" />
                  <span className="mono-label text-[#7A8CA0]">LOADING 3D SOLID</span>
                </div>
              )}
            </div>

            <div className="flex justify-between items-center bg-white/50 p-4 rounded-[4px] border border-[#D8E4EE]">
              <div>
                <h4 className="font-mono text-sm font-semibold text-[#0A0E12]">
                  {cadResult?.stl_filename || `${template}.stl`}
                </h4>
                <p className="mono-label text-[10px] text-[#7A8CA0] mt-1">
                  WATERTIGHT SOLID &bull; {((cadResult?.volume_mm3 || 0) / 1000).toFixed(2)} CM³
                </p>
              </div>
              <div className="flex space-x-3">
                {cadResult?.step_url && (
                  <a
                    href={`${API_BASE}${cadResult.step_url}`}
                    download
                    className="inline-flex items-center px-4 py-2 border border-[#D8E4EE] text-xs font-display font-extrabold uppercase tracking-wide rounded-[4px] text-[#0A0E12] bg-white hover:bg-gray-50 transition-colors"
                  >
                    Download STEP
                  </a>
                )}
                <a
                  href={`${API_BASE}${cadResult?.stl_url || ""}`}
                  download
                  className="inline-flex items-center px-4 py-2 text-xs font-display font-extrabold uppercase tracking-wide rounded-[4px] text-[#0A0E12] bg-[#A2B9EE] hover:bg-[#0A0E12] hover:text-white transition-colors"
                >
                  <Download className="w-4 h-4 mr-2" /> Download STL
                </a>
              </div>
            </div>

            <div className="mt-8 flex justify-start">
              <button
                onClick={() => {
                  setStep(1);
                  setPhotos({ front: null, side: null, back: null });
                  setCadResult(null);
                }}
                className="group flex items-center gap-2 font-display text-sm font-extrabold uppercase tracking-wide text-[#0A0E12] transition-colors hover:text-[#A2B9EE] cursor-pointer"
              >
                <span>&larr;</span> START NEW REPAIR
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
