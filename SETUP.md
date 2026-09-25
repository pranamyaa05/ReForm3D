# ReForm3D — First-Time Setup & Developer Guide (`SETUP.md`)

This guide walks you step-by-step through setting up **ReForm3D** from scratch on **Windows** (as well as macOS/Linux), even if you have never generated a Google Gemini API key or installed CadQuery before.

---

## 1. Prerequisites & Python Version (Critical for CadQuery on Windows)

### Why Python 3.10 – 3.12 is required
Stage 3 of ReForm3D uses **CadQuery** (`cadquery>=2.4`), which is **not** a pure-Python package. Under the hood, CadQuery wraps the C++ **OpenCascade Technology (OCCT)** CAD kernel via compiled binary wheels (`cadquery-ocp` / `vtk` / `casadi` / `nlopt`).

- **Recommended Python version on Windows:** **Python 3.10 or 3.11 (64-bit)**.
- **Important:** Newer bleeding-edge Python releases (such as Python 3.13+) often do not have pre-built `cadquery-ocp` binary wheels on PyPI yet, which will cause `pip install cadquery` to fail trying to compile OpenCascade from C++ source.
- **Windows OS-level runtime dependency:** CadQuery and OpenCV binary wheels on Windows require the **Microsoft Visual C++ Redistributable (2015–2022, x64)**. Most Windows 10/11 machines already have this installed; if you ever see `ImportError: DLL load failed while importing OCP`, install [`vc_redist.x64.exe`](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) from Microsoft.

Check your active Python version in PowerShell:
```powershell
python --version
# Expected: Python 3.10.x or 3.11.x (64-bit)
```

> **Note if you have multiple Python versions installed on Windows:** Always prefix commands with `python -m` (for example `python -m pip ...` and `python -m pytest ...`) so Windows uses your Python 3.10 interpreter rather than another Python installation on `PATH`.

---

## 2. Installing Dependencies

From the project root (`E:\PROJECTS\ReForm3D`), create/activate a virtual environment (optional if already installed in your Python 3.10 environment) and install `requirements.txt`:

```powershell
# Upgrade pip and wheel so binary wheels for cadquery-ocp are selected automatically
python -m pip install --upgrade pip setuptools wheel

# Install all ReForm3D dependencies
python -m pip install -r requirements.txt
```

### What gets installed and why it takes a moment
1. **CadQuery & OpenCascade (`cadquery`, `cadquery-ocp`, `trimesh`):** Downloads ~250–350 MB of precompiled C++ CAD geometry binaries (`cadquery-ocp` and `vtk`).
2. **Background Segmentation (`rembg[cpu]`, `onnxruntime`, `opencv-python-headless`):** Provides deterministic U²-Net background cleanup and CLAHE exposure normalization for Stage 1.5.
3. **Google GenAI SDK (`google-genai>=2.0`):** Official SDK for Stage 2 structured-output vision diagnosis (`DiagnosisResult` schema).
4. **FastAPI & Uvicorn (`fastapi`, `uvicorn[standard]`, `python-multipart`):** Serves the REST API and mobile-first web client.

---

## 3. Getting a Google Gemini API Key & Configuring `.env`

ReForm3D **never** hardcodes API keys, model names, or thresholds in source code. Everything is loaded from `.env` in the project root (`E:\PROJECTS\ReForm3D\.env`), which is listed in `.gitignore` so your key is never committed to Git.

### Step 3.1 — Generate a Free Gemini API Key (First-Timer Walkthrough)
1. Open **[Google AI Studio](https://aistudio.google.com/apikey)** in your browser and sign in with your Google account.
2. Click the **"Create API key"** button in the top-right corner.
3. Choose **"Create API key in new project"** (or select an existing Google Cloud project).
4. Copy the generated key string (it starts with `AIza...`).

### Step 3.2 — Put the Key in `.env`
1. In the project root (`E:\PROJECTS\ReForm3D`), copy `.env.example` to `.env` if `.env` does not already exist:
   ```powershell
   Copy-Item .env.example .env
   ```
2. Open `E:\PROJECTS\ReForm3D\.env` in your editor and replace the placeholder on line 15 (`GEMINI_API_KEY=your_gemini_api_key_here`) with your real key:
   ```ini
   GEMINI_API_KEY=AIzaSyYourActualKeyHere
   GEMINI_MODEL=gemini-3.8-flash
   USE_MOCK_VLM=false
   ```

> **Offline / Local Dev Mode without an API Key:**
> If you want to run the app or automated tests offline without calling the live Gemini API, set:
> ```ini
> USE_MOCK_VLM=true
> ```
> When `USE_MOCK_VLM=false`, ReForm3D's startup validator (`verify_required_env`) checks `GEMINI_API_KEY` and **fails fast** if the key is missing, blank, or still set to `your_gemini_api_key_here`.

---

## 4. Stage 1.5 Background-Removal Model Downloads (Disk & RAM Footprint)

Stage 1.5 uses **`rembg`** (backed by **ONNX Runtime** on CPU) to isolate the broken object from background clutter before sending photos to the VLM, followed by a programmatic **reference-retention safety check** inside your marked bounding box.

- **Where weights are stored:** On the very first Stage 1.5 run, `rembg` automatically downloads the configured ONNX segmentation weights into your user home directory at `C:\Users\<YourUser>\.u2net\`.
- **Configurable models (`REMBG_MODEL` in `.env`):**
  | `REMBG_MODEL` value | Disk Download Size | Peak RAM Footprint | Notes |
  | :--- | :--- | :--- | :--- |
  | `u2netp` *(default)* | **~4.7 MB** | **~200–300 MB** | Fast, lightweight U²-Net Pocket variant. Recommended for phones/laptops. |
  | `u2net` | **~176 MB** | **~500–700 MB** | Full U²-Net model; sharper contours on complex backgrounds. |
  | `isnet-general-use` | **~169 MB** | **~500–700 MB** | High-precision general object segmentation. |

- **Disabling Stage 1.5 (`ENABLE_IMAGE_ENHANCEMENT=false`):**
  If you are on a slow connection or low-RAM machine, set `ENABLE_IMAGE_ENHANCEMENT=false` in `.env`. Stage 1.5 will cleanly skip enhancement, report `enhancement_skipped=true`, and pass your untouched raw images directly to Stage 2.

---

## 5. Running the Application

Start the server from `E:\PROJECTS\ReForm3D`:

```powershell
python run.py
```
*(Or via Uvicorn directly: `python -m uvicorn reform3d.app:app --host 127.0.0.1 --port 8000`)*

Then open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser:
1. **Stage 1 (Capture):** Select your scale reference (`coin`, `credit_card`, `ruler`, or `other`), capture or upload the 3 guided angles (`straight_on`, `angled`, `mating_surface`), drag a bounding box over your reference object on the canvas, and check the quality verdict (or click **"Auto-Fill 3 Demo Photos"** for a 1-click desktop test).
2. **Stage 1.5 (Enhance):** Inspect the Raw vs. Enhanced comparison and reference-retention ratio.
3. **Stage 2 (Diagnose & Confirm):** Review the Gemini diagnosis, edit any measurements (low-confidence fields are highlighted in amber), check the confirmation box (`user_confirmed = true`), and click **Generate Watertight 3D CAD**.
4. **Stage 3 (Preview & Download):** Rotate/zoom the generated part in the interactive **Three.js 3D STL Viewer** and download the verified **`.stl`** and **`.step`** files.

---

## 6. Running the Automated Test Suite (`pytest`)

Run the full T1–T9 test checklist using the Python 3.10 interpreter:

```powershell
python -m pytest -v tests/test_reform3d_pipeline.py
```
