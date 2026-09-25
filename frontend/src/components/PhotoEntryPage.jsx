import { useState, useRef } from 'react';
import { Camera, Image as ImageIcon, CheckCircle2, ChevronRight, Download, Box, Activity } from 'lucide-react';
import STLViewer from './STLViewer';

export default function PhotoEntryPage() {
  const [step, setStep] = useState(1);
  const [photos, setPhotos] = useState({
    front: null  ,
    side: null  ,
    back: null  ,
  });
  const [photoFiles, setPhotoFiles] = useState({
    front: null  ,
    side: null  ,
    back: null  ,
  });
  const [isProcessing, setIsProcessing] = useState(false);
  const [repairData, setRepairData] = useState(null);

  const handlePhotoUpload = (view, e) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      const url = URL.createObjectURL(file);
      setPhotos(prev => ({ ...prev, [view]: url }));
      setPhotoFiles(prev => ({ ...prev, [view]: file }));
    }
  };

  const allPhotosUploaded = photos.front && photos.side && photos.back;

  const handleProcess = async () => {
    setStep(2);
    setIsProcessing(true);
    try {
      const formData = new FormData();
      if (photoFiles.front) formData.append("file", photoFiles.front);
      const res = await fetch("http://127.0.0.1:8000/api/repair", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      setRepairData(data);
      setStep(3);
    } catch (e) {
      console.error(e);
      alert("Failed to process repair.");
      setStep(1);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto">
      {/* Stepper */}
      <div className="mb-8">
        <div className="flex items-center justify-between">
          {[
            { num: 1, title: 'Capture' },
            { num: 2, title: 'Process' },
            { num: 3, title: 'Result' }
          ].map((s, idx) => (
            <div key={s.num} className="flex items-center flex-1">
              <div className={`flex items-center justify-center w-10 h-10 rounded-full border-2 
                ${step >= s.num ? 'border-[#A2B9EE] bg-[#A2B9EE] text-[#0A0E12]' : 'border-[#D8E4EE] text-[#7A8CA0]'}`}>
                {step > s.num ? <CheckCircle2 className="w-6 h-6" /> : <span className="font-mono text-sm font-semibold">{s.num}</span>}
              </div>
              <span className={`ml-3 font-medium ${step >= s.num ? 'text-gray-900' : 'text-gray-400'}`}>
                {s.title}
              </span>
              {idx < 2 && <div className="flex-1 mx-4 h-0.5 bg-gray-200" />}
            </div>
          ))}
        </div>
      </div>

      <div className="bg-[#F0F7FA]/85 backdrop-blur-md rounded-xl border border-[#D8E4EE] overflow-hidden">
        {step === 1 && (
          <div className="p-8">
            <h2 className="font-display text-2xl font-black uppercase tracking-tight text-[#0A0E12] mb-4">Step 1: Capture Object</h2>
            <p className="text-[#52667A] mb-8 leading-relaxed">
              Please take clear, well-lit photos of the object you want to repair or adapt.
              Use a solid, uncluttered background if possible.
            </p>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {(['front', 'side', 'back'] ).map((view) => (
                <div key={view} className="flex flex-col">
                  <span className="mono-label text-[10px] text-[#7A8CA0] uppercase mb-2">{view} View</span>
                  <div className="relative border-2 border-dashed border-[#D8E4EE] rounded-lg bg-white/50 flex flex-col items-center justify-center aspect-[3/4] hover:bg-white transition-colors group cursor-pointer">
                    {photos[view] ? (
                      <img src={photos[view]} alt={`${view} view`} className="w-full h-full object-cover rounded-lg" />
                    ) : (
                      <div className="text-center p-4">
                        <Camera className="mx-auto h-12 w-12 text-gray-400 mb-2 group-hover:text-blue-500 transition-colors" />
                        <span className="text-sm text-gray-500">Tap to take photo</span>
                      </div>
                    )}
                    <input 
                      type="file" 
                      accept="image/*" 
                      capture="environment"
                      onChange={(e) => handlePhotoUpload(view, e)}
                      className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                    />
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-8 flex justify-end">
              <button 
                onClick={handleProcess}
                disabled={!allPhotosUploaded}
                className={`group relative inline-flex cursor-pointer items-center gap-3 rounded-[4px] px-7 py-4 font-display text-sm font-extrabold uppercase tracking-wide transition-colors duration-300
                  ${allPhotosUploaded ? 'bg-[#A2B9EE] text-[#0A0E12] hover:bg-[#0A0E12] hover:text-white' : 'bg-[#D8E4EE] cursor-not-allowed text-[#7A8CA0]'}`}
              >
                Continue <ChevronRight className="ml-2 w-4 h-4 transition-transform group-hover:translate-x-1" />
              </button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="p-8 text-center">
            <h2 className="font-display text-2xl font-black uppercase tracking-tight text-[#0A0E12] mb-4">Step 2: Processing & Enhancement</h2>
            <p className="text-[#52667A] mb-12 max-w-2xl mx-auto leading-relaxed">
              We are analyzing your photos to remove backgrounds, correct lighting, and extract the best possible geometry.
            </p>

            <div className="flex justify-center items-center space-x-12 mb-12">
              <div className="flex flex-col items-center">
                <div className="w-24 h-24 rounded-full bg-[#E5EEFF] flex items-center justify-center animate-pulse mb-4">
                  <ImageIcon className="w-10 h-10 text-[#A2B9EE]" />
                </div>
                <span className="mono-label text-[10px] text-[#0A0E12]">ISOLATING OBJECT</span>
              </div>
              <Activity className="w-8 h-8 text-[#D8E4EE]" />
              <div className="flex flex-col items-center">
                <div className="w-24 h-24 rounded-full bg-[#B4E4E6]/20 flex items-center justify-center animate-pulse mb-4" style={{animationDelay: '0.2s'}}>
                  <Box className="w-10 h-10 text-[#B4E4E6]" />
                </div>
                <span className="mono-label text-[10px] text-[#0A0E12]">INFERRING CAD</span>
              </div>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="p-8">
            <h2 className="font-display text-2xl font-black uppercase tracking-tight text-[#0A0E12] mb-4">Step 3: 3D Model Generated</h2>
            <p className="text-[#52667A] mb-8 leading-relaxed">
              Your repair attachment has been successfully generated. Preview the model below and download the STL file for printing.
            </p>

            <div className="aspect-video bg-[#0A0E12] rounded-xl mb-8 flex items-center justify-center relative overflow-hidden shadow-[inset_0_2px_20px_rgba(0,0,0,0.5)]">
              {repairData?.stl_url ? (
                <STLViewer url={repairData.stl_url} />
              ) : (
                <div className="relative z-10 flex flex-col items-center">
                  <Box className="w-16 h-16 text-[#A2B9EE] mb-4 animate-bounce" />
                  <span className="mono-label text-[#7A8CA0]">FAILED TO LOAD STL</span>
                </div>
              )}
            </div>

            <div className="flex justify-between items-center bg-white/50 p-4 rounded-[4px] border border-[#D8E4EE]">
              <div>
                <h4 className="font-mono text-sm font-semibold text-[#0A0E12]">
                  {repairData?.diagnosis?.suggested_template || "friction_fit_collar"}.stl
                </h4>
                <p className="mono-label text-[10px] text-[#7A8CA0] mt-1">
                  {repairData?.diagnosis?.failure_diagnosis || "Watertight volume: 14.2 cm³"}
                </p>
              </div>
              <div className="flex space-x-3">
                <button className="inline-flex items-center px-4 py-2 border border-[#D8E4EE] text-xs font-display font-extrabold uppercase tracking-wide rounded-[4px] text-[#0A0E12] bg-white hover:bg-gray-50 cursor-pointer transition-colors">
                  Save to Session
                </button>
                <a href={repairData?.stl_url} download className="inline-flex items-center px-4 py-2 text-xs font-display font-extrabold uppercase tracking-wide rounded-[4px] text-[#0A0E12] bg-[#A2B9EE] hover:bg-[#0A0E12] hover:text-white cursor-pointer transition-colors">
                  <Download className="w-4 h-4 mr-2" /> Download STL
                </a>
              </div>
            </div>
            
            <div className="mt-8 flex justify-start">
              <button 
                onClick={() => {
                  setStep(1);
                  setPhotos({front: null, side: null, back: null});
                  setPhotoFiles({front: null, side: null, back: null});
                  setRepairData(null);
                }}
                className="group flex items-center gap-2 font-display text-sm font-extrabold uppercase tracking-wide text-[#0A0E12] transition-colors hover:text-[#A2B9EE] cursor-pointer"
              >
                <span className="transition-transform group-hover:-translate-x-1">&larr;</span> START NEW REPAIR
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
