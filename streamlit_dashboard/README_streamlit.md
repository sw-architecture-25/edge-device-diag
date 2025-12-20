# Streamlit Dashboard (Edge Device Diag)

## Run
1) Start API server
   - `python app.py` (FastAPI on http://localhost:8000)

2) Start dashboard
   - `pip install streamlit requests pandas`
   - `streamlit run streamlit_dashboard.py`

## Features
- Auto refresh (sidebar)
- Trend chart: T1 / μ / dynamic_threshold / final_threshold
- Alerts table with filters
- Threshold control:
  - Apply manual: PUT /thresholds with numeric value
  - Apply dynamic: PUT /thresholds with value="dynamic" (if supported)
