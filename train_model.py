import pandas as pd
from sklearn.ensemble import IsolationForest
import joblib

# Load ICMP feature data
df = pd.read_csv("data/icmp_live.csv")

features = ['rtt', 'packet_loss', 'icmp_rate', 'ttl', 'ttl_variance']
X = df[features]


# Train Isolation Forest (unsupervised)
model = IsolationForest(
    n_estimators=100,
    contamination=0.01,
    random_state=42
)

model.fit(X)

# Save trained model
joblib.dump(model, "model/icmp_model.pkl")

print("✅ ICMP ML model trained and saved successfully")

