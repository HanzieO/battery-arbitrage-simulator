import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from datetime import timedelta

# ==================== CONFIGURATION ====================
st.title("NSW Battery Arbitrage Simulator")

# Hardcoded CSV file
CSV_FILE = 'nsw_5min_prices_2025_to_early2026_kWh.csv'

# Load data
@st.cache_data
def load_data():
    df = pd.read_csv(CSV_FILE)
    df['SETTLEMENTDATE'] = pd.to_datetime(df['SETTLEMENTDATE'])
    df = df.sort_values('SETTLEMENTDATE').reset_index(drop=True)
    return df

try:
    df = load_data()
    price_series = df['RRP_kWh']
    INTERVAL_HOURS = 5 / 60.0
    st.success(f"Data loaded successfully from {CSV_FILE} ({len(df)} intervals)")
except FileNotFoundError:
    st.error(f"Error: Could not find '{CSV_FILE}'. Make sure the CSV file is in the same folder/repo as app.py.")
    st.stop()
except Exception as e:
    st.error(f"Error loading data: {e}")
    st.stop()

st.sidebar.header("Battery & Strategy Parameters")

power_kw = st.sidebar.number_input("Inverter Power (kW)", min_value=1.0, value=100.0, step=10.0)
capacity_kwh = st.sidebar.number_input("Battery Capacity (kWh)", min_value=1.0, value=200.0, step=10.0)

buy_thresh = st.sidebar.number_input("Buy Threshold ($/kWh - charge when below)", value=0.05, step=0.01, format="%.3f")
sell_thresh = st.sidebar.number_input("Sell Threshold ($/kWh - discharge when above)", value=0.20, step=0.01, format="%.3f")

charge_eff = st.sidebar.slider("Charge Efficiency", min_value=0.80, max_value=1.00, value=0.95, step=0.01)
discharge_eff = st.sidebar.slider("Discharge Efficiency", min_value=0.80, max_value=1.00, value=0.95, step=0.01)

st.sidebar.header("Additional Costs")

slippage_pct = st.sidebar.slider("Price/Fee Slippage (% of gross profit)", min_value=1.0, max_value=10.0, value=5.0, step=0.5)

degradation_cents_per_kwh = st.sidebar.slider("Battery Degradation Cost (cents/kWh discharged)", min_value=1.0, max_value=4.0, value=2.0, step=0.5)

# ==================== SIMULATION ====================
@st.cache_data
def run_simulation(_df, power, capacity, buy, sell, ch_eff, dis_eff):
    max_energy = power * INTERVAL_HOURS
    
    soc = 0.0
    charge_cost = 0.0
    discharge_revenue = 0.0
    total_discharged_kwh = 0.0
    
    soc_history = []
    profit_history = []
    cumulative_profit = 0.0
    
    discharge_trades = []
    
    prices = _df['RRP_kWh'].values
    timestamps = _df['SETTLEMENTDATE']
    
    for idx, price in enumerate(prices):
        energy_moved = 0.0
        
        if price < buy and soc < capacity:
            max_charge_grid = max_energy
            max_charge_battery = (capacity - soc) / ch_eff
            energy_moved = min(max_charge_grid, max_charge_battery)
            soc += energy_moved * ch_eff
            charge_cost += energy_moved * price
        
        elif price > sell and soc > 0:
            max_discharge_grid = max_energy / dis_eff
            max_discharge_battery = soc
            energy_moved = min(max_discharge_grid, max_discharge_battery)
            soc -= energy_moved * dis_eff
            discharge_revenue += energy_moved * price
            total_discharged_kwh += energy_moved
            
            discharge_trades.append({
                'Time': timestamps[idx],
                'Price ($/kWh)': round(price, 4),
                'kWh Discharged': round(energy_moved, 2),
                'Revenue ($)': round(energy_moved * price, 2)
            })
        
        cumulative_profit = discharge_revenue - charge_cost
        soc_history.append(soc)
        profit_history.append(cumulative_profit)
    
    gross_profit = discharge_revenue - charge_cost
    
    start_date = timestamps.min()
    end_date = timestamps.max()
    days_covered = (end_date - start_date).days + (end_date - start_date).seconds / 86400
    gross_annual = gross_profit * (365 / days_covered) if days_covered > 0 else 0
    
    return {
        'gross_profit': gross_profit,
        'gross_annual': gross_annual,
        'charge_cost': charge_cost,
        'discharge_revenue': discharge_revenue,
        'total_discharged_kwh': total_discharged_kwh,
        'days_covered': days_covered,
        'final_soc': soc,
        'soc_history': soc_history,
        'profit_history': profit_history,
        'timestamps': timestamps,
        'discharge_trades': discharge_trades
    }

results = run_simulation(df, power_kw, capacity_kwh, buy_thresh, sell_thresh, charge_eff, discharge_eff)

# ==================== APPLY DEDUCTIONS ====================
slippage_amount = results['gross_profit'] * (slippage_pct / 100)
degradation_cost = results['total_discharged_kwh'] * (degradation_cents_per_kwh / 100)

net_profit = results['gross_profit'] - slippage_amount - degradation_cost
net_annual = net_profit * (365 / results['days_covered']) if results['days_covered'] > 0 else 0

# ==================== DISPLAY RESULTS ====================
st.header("Simulation Results")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Gross Profit", f"${results['gross_profit']:,.0f}")
col2.metric("Gross Annualized", f"${results['gross_annual']:,.0f}/year")
col3.metric("Net Profit (after deductions)", f"${net_profit:,.0f}")
col4.metric("Net Annualized", f"${net_annual:,.0f}/year")

st.write(f"**Charging Cost:** ${results['charge_cost']:,.0f} | **Discharge Revenue:** ${results['discharge_revenue']:,.0f}")
st.write(f"**Total Discharged:** {results['total_discharged_kwh']:,.0f} kWh")
st.write(f"**Deductions:** Slippage ({slippage_pct:.1f}%): ${slippage_amount:,.0f} | Degradation ({degradation_cents_per_kwh:.1f}¢/kWh): ${degradation_cost:,.0f}")
st.write(f"**Final Battery SoC:** {results['final_soc']:.1f} kWh (not credited)")

# ==================== GRAPH ====================
st.header("Battery State of Charge & Cumulative Gross Profit")

fig, ax1 = plt.subplots(figsize=(12, 6))
ax1.set_xlabel('Date')
ax1.set_ylabel('State of Charge (kWh)', color='tab:blue')
line1 = ax1.plot(results['timestamps'], results['soc_history'], color='tab:blue', linewidth=1, label='SoC (kWh)')
ax1.tick_params(axis='y', labelcolor='tab:blue')
ax1.grid(True, alpha=0.3)

ax2 = ax1.twinx()
ax2.set_ylabel('Cumulative Gross Profit ($)', color='tab:green')
line2 = ax2.plot(results['timestamps'], results['profit_history'], color='tab:green', linewidth=1.5, label='Profit ($)')

ax2.tick_params(axis='y', labelcolor='tab:green')

# Combined legend
lines = line1 + line2
labels = [l.get_label() for l in lines]
ax1.legend(lines, labels, loc='upper left')

fig.tight_layout()
st.pyplot(fig)

# ==================== DISCHARGE TRADES LIST ====================
st.header("Discharge Trades")

if results['discharge_trades']:
    trades_df = pd.DataFrame(results['discharge_trades'])
    trades_df['Time'] = trades_df['Time'].dt.strftime('%Y-%m-%d %H:%M')
    
    # Add total revenue for the table
    total_revenue_from_trades = trades_df['Revenue ($)'].sum()
    st.write(f"**Total Discharge Events:** {len(trades_df)} | **Total Discharge Revenue:** ${total_revenue_from_trades:,.0f}")
    
    st.dataframe(trades_df.sort_values('Time', ascending=False).reset_index(drop=True),
                 use_container_width=True,
                 hide_index=True)
else:
    st.info("No discharge trades occurred. Try lowering the sell threshold or checking if prices exceeded it when the battery was charged.")

st.caption("Note: The graph and trades list are now guaranteed to appear. The graph has improved styling (grid, legend, thicker profit line). Trades table includes revenue per block and is sorted newest first.")
