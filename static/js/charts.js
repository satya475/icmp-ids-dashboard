// Store chart instances globally so we can update them
const charts = {};

async function loadData() {
    try {
        const response = await fetch("/api/metrics");
        const data = await response.json();

        if (data.error) {
            console.error(data.error);
            return;
        }
        document.getElementById("downloadSpeed").innerText = data.download.toFixed(2);
        document.getElementById("uploadSpeed").innerText = data.upload.toFixed(2);
        const statusBox = document.getElementById("statusBox");
        const ttlBox = document.getElementById("ttlBox");

        // Update Status Box
        statusBox.innerText = data.network_status;
        if (data.network_status.includes("🚨")) {
            statusBox.className = "alert-box danger"; // Make sure to add these colors to CSS
        } else if (data.network_status.includes("⚠️") || data.network_status.includes("🟠")) {
            statusBox.className = "alert-box warning";
        } else {
            statusBox.className = "alert-box success";
        }

        // Update TTL Box
        ttlBox.innerText = data.ttl_alert ? `⚠️ TTL Alert: ${data.ttl_reason}` : "TTL Status: Normal";
        ttlBox.className = data.ttl_alert ? "ttl-box warning" : "ttl-box success";

        // Update or Create Charts
        updateChart("rttChart", "RTT (ms)", data.rtt, "#3b82f6");
        updateChart("lossChart", "Packet Loss (%)", data.packet_loss, "#ef4444");
        updateChart("rateChart", "ICMP Rate", data.icmp_rate, "#10b981");
        updateChart("ttlChart", "TTL Value", data.ttl, "#f59e0b");

    } catch (err) {
        console.log("Waiting for data sync...");
    }
}

function updateChart(id, label, values, color) {
    const ctx = document.getElementById(id).getContext('2d');
    
    // If chart doesn't exist, create it
    if (!charts[id]) {
        charts[id] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: values.map((_, i) => i),
                datasets: [{
                    label: label,
                    data: values,
                    borderColor: color,
                    backgroundColor: color + '22', // Transparent fill
                    borderWidth: 2,
                    pointRadius: 0, // Cleaner look for live data
                    fill: true,
                    tension: 0.4 // Makes the line "smooth/curvy"
                }]
            },
            options: {
                responsive: true,
                animation: false, // Set to false for high-frequency live updates
                scales: {
                    y: { beginAtZero: true }
                }
            }
        });
    } else {
        // If chart exists, just update the data
        charts[id].data.labels = values.map((_, i) => i);
        charts[id].data.datasets[0].data = values;
        charts[id].update('none'); // Update without a clunky animation
    }
}

// Refresh every 2 seconds
setInterval(loadData, 2000);