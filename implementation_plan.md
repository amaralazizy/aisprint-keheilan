# Unified Streamlit Frontend Plan

You requested a new, simple frontend (using Streamlit or Gradio) that includes both our newly developed Crop Advisory models AND your friends' original "Model 1" Land Investment models. 

I propose using **Streamlit**, as it is excellent for quickly building data-rich, interactive dashboards in Python.

## User Review Required

> [!IMPORTANT]  
> Please review the proposed layout for the Streamlit App. It will serve as a single unified dashboard that connects to both codebases. Do you approve of this structure?

## Open Questions

1. **Dependency:** Streamlit needs to be installed. Once I build the file, you will need to run `pip install streamlit` in your environment. Are you okay with that?
2. **Database:** For the "Model 1" tab, I will connect directly to the existing `model1_land.db` database so you can select real parcels that are already in the system. Is this correct?

## Proposed Changes

### 1. Create `app.py` in the Root Directory
I will create a new file `d:\kheilan\aisprint-keheilan\app.py`. This will be the main Streamlit application.

### 2. Sidebar Navigation
The app will have a sidebar allowing the user to switch between two main pages/modes:
- **🌱 Crop Advisory (Our Models)**
- **💰 Land Investment (Model 1)**

### 3. Page 1: Crop Advisory (Our Models)
This page will expose the work we did:
- **Inputs:** A form to enter Latitude, Longitude, Area (Feddans), Soil Type, Water Source, and Budget.
- **Option A: Evaluate Specific Crop.** The user enters a Target Crop (e.g., "mango") and hits "Evaluate". It runs our 12-stage pipeline and displays the yield, revenue, confidence, and narrative.
- **Option B: Find Best Crop.** If left blank, the user hits "Find Best Crop". The app runs our new `run_best_crop` logic (discovers top 3 crops, evaluates all of them, and declares a winner).

### 4. Page 2: Land Investment (Model 1)
This page will expose the AI tools your friends built in `packages/model1_land`:
- **Parcel Selector:** A dropdown that loads all existing parcels from the `model1_land` database.
- **Action 1: Evaluate Risk.** A button that triggers `model1_land.ai.risk_model.apply()`. It will display the AI-determined Risk Tier (e.g., Low, Medium, High) and the JSON risk factors.
- **Action 2: Calculate Undervaluation.** A button that triggers `model1_land.ai.undervaluation.apply()`. It will display the AI-determined market trend and undervaluation percentage.

## Verification Plan
Once built, you will run:
```bash
pip install streamlit
streamlit run app.py
```
This will open a beautiful web interface in your browser containing everything!
