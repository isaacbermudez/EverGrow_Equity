# backend/app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd
import time

app = Flask(__name__)
CORS(app)

@app.route('/api/analyze-portfolio', methods=['POST'])
def analyze_portfolio_backend():
    print("\n--- Backend Request Received ---")
    try:
        portfolio_data_from_frontend = request.json.get('portfolio', [])
        print(f"Backend: Frontend sent {len(portfolio_data_from_frontend)} portfolio items.")
        
        if not isinstance(portfolio_data_from_frontend, list) or not portfolio_data_from_frontend:
            print("Backend Error: Invalid or empty portfolio data provided by frontend.")
            return jsonify({'error': 'Invalid or empty portfolio data provided'}), 400

        results = {}
        symbols_to_fetch = list(set([item['symbol'] for item in portfolio_data_from_frontend if 'symbol' in item]))
        print(f"Backend: Unique symbols to fetch: {symbols_to_fetch}")

        if not symbols_to_fetch:
            print("Backend Error: No valid symbols found in portfolio to fetch (after parsing frontend data).")
            return jsonify({'error': 'No valid symbols found in portfolio to fetch'}), 400
        
        raw_stock_info = {}
        for symbol in symbols_to_fetch:
            print(f"Backend: Attempting to fetch data for {symbol} from yfinance...")
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info 
                raw_stock_info[symbol] = info
                print(f"Backend: Successfully fetched info for {symbol}.")
                # Log the actual price data received from yfinance
                print(f"Backend: yfinance for {symbol} - currentPrice: {info.get('currentPrice')}, previousClose: {info.get('previousClose')}")
            except Exception as e:
                print(f"Backend Error: Failed to fetch yfinance data for {symbol}: {e}")
                raw_stock_info[symbol] = None # Mark as failed

        # Process data for each portfolio item based on fetched raw info
        for item in portfolio_data_from_frontend:
            symbol = item.get('symbol')
            
            # Extract Category and Sector directly from the input item payload (from frontend)
            input_category = item.get('Category', 'N/A')
            input_sector = item.get('Sector', 'N/A')
            
            # Extract CI and Holdings from the input item
            ci = item.get('CI') # Cost Index per holding
            holdings = item.get('holdings')

            # --- Initialize all values to their defaults (None/0) ---
            current_price = None # Will be set to actual currentPrice or previousClose
            previous_close = None # Will be set to actual previousClose
            market_cap = None
            pe_ratio = None
            dividend_yield = 0
            fifty_two_week_high = None
            fifty_two_week_low = None
            volume = None
            average_volume = None
            yfinance_industry = None
            
            calculated_invested_amount = 0
            calculated_current_value = 0 
            calculated_gain_loss = 0     
            calculated_return_percent = 0 
            calculated_avg_cost = 0 
            
            day_change = 0
            day_change_percent = 0

            error_message = None 

            # First, calculate invested amount and avgCost if CI and holdings are valid
            if ci is not None and holdings is not None:
                calculated_invested_amount = ci * holdings
                calculated_avg_cost = ci # CI is the average cost per holding
                print(f"Backend: {symbol}: CI={ci}, Holdings={holdings}, Calculated Invested Amount (CI*Holdings) = {calculated_invested_amount:.2f}")
            else:
                error_message = f'Missing CI or Holdings for {symbol}. Cannot calculate base values.'
                print(f"Backend: {symbol}: Missing CI or Holdings. Base values set to 0 and error.")


            # Attempt to fetch live data and perform calculations
            if symbol and raw_stock_info.get(symbol):
                info = raw_stock_info[symbol]
                
                temp_current_price = info.get('currentPrice')
                temp_previous_close = info.get('previousClose') # Always get previousClose if available

                print(f"Backend: {symbol}: yfinance info fetched. Raw currentPrice: {temp_current_price}, Raw previousClose: {temp_previous_close}")

                if temp_current_price is not None and temp_previous_close is not None:
                    # Case 1: Both currentPrice and previousClose are available (ideal scenario)
                    current_price = temp_current_price
                    previous_close = temp_previous_close
                    print(f"Backend: {symbol}: Using actual live currentPrice.")

                elif temp_current_price is None and temp_previous_close is not None:
                    # Case 2: currentPrice is missing, but previousClose is available (fallback)
                    current_price = temp_previous_close # Use previousClose as currentPrice
                    previous_close = temp_previous_close # Keep previousClose as is for calculation context
                    error_message = f'Current price missing for {symbol}. Using previousClose as currentPrice for calculations.'
                    print(f"Backend: {symbol}: {error_message}")
                    day_change = 0 # No actual day change when using fallback
                    day_change_percent = 0 # No actual day change when using fallback
                    
                else:
                    # Case 3: Both currentPrice and previousClose are missing, or only currentPrice is missing and previousClose is also missing.
                    error_message = f'Could not retrieve any crucial live price data (currentPrice/previousClose) for {symbol}.'
                    print(f"Backend: {symbol}: {error_message}. All live-dependent values remain 0.")
                    # All calculated_... values (currentValue, gainLoss, returnPercent) remain 0 as initialized.


                # Populate other yfinance-derived fields if info was generally available
                if current_price is not None: # Only if we have *some* price to work with
                    market_cap = info.get('marketCap')
                    pe_ratio = info.get('trailingPE') or info.get('forwardPE')
                    dividend_yield = info.get('dividendYield') * 100 if info.get('dividendYield') is not None else 0
                    fifty_two_week_high = info.get('fiftyTwoWeekHigh')
                    fifty_two_week_low = info.get('fiftyTwoWeekLow')
                    volume = info.get('volume')
                    average_volume = info.get('averageVolume10Days') or info.get('averageVolume')
                    yfinance_industry = info.get('industry')

                # Perform calculations only if current_price is now available (either live or fallback)
                if current_price is not None and holdings is not None and calculated_invested_amount > 0:
                    calculated_current_value = current_price * holdings
                    calculated_gain_loss = calculated_current_value - calculated_invested_amount
                    calculated_return_percent = (calculated_gain_loss / calculated_invested_amount) * 100 if calculated_invested_amount != 0 else 0
                    print(f"Backend: {symbol}: Calculated Current Value: {calculated_current_value:.2f}, Gain/Loss: {calculated_gain_loss:.2f}, Return%: {calculated_return_percent:.2f}%")
                else:
                    # If current_price is still None (no fallback possible), or holdings/invested_amount are invalid
                    print(f"Backend: {symbol}: Cannot perform live calculations. Current Value, Gain/Loss, Return% set to 0.")

            else:
                # Case: yfinance entirely failed to fetch info for this symbol
                error_message = f'Could not retrieve any data from yfinance for {symbol} (symbol not found or API issue).'
                print(f"Backend: {symbol}: {error_message}. All values remain 0.")
                # All calculated_... values remain 0 as initialized, per strict requirement.

            # Compile results for this symbol
            results[symbol] = {
                'symbol': symbol,
                'bolsa': item.get('bolsa', 'N/A'),
                'CI': ci, 
                'holdings': holdings,
                'invested_amount': calculated_invested_amount, 
                'currentPrice': current_price, 
                'previousClose': previous_close, 
                'dayChange': day_change, 
                'dayChangePercent': day_change_percent, 
                'marketCap': market_cap, 
                'peRatio': pe_ratio, 
                'dividendYield': dividend_yield, 
                'fiftyTwoWeekHigh': fifty_two_week_high, 
                'fiftyTwoWeekLow': fifty_two_week_low, 
                'volume': volume, 
                'averageVolume': average_volume, 
                
                'sector': input_sector,    
                'category': input_category, 
                'yfinance_industry': yfinance_industry, 

                'currentValue': calculated_current_value, 
                'gainLoss': calculated_gain_loss,         
                'returnPercent': calculated_return_percent, 
                'avgCost': calculated_avg_cost, 
                'error': error_message 
            }
            print(f"Backend: Final processed data for {symbol}: {results[symbol]}")

        print("\n--- Backend Analysis Complete. Sending Response ---")
        return jsonify({'success': True, 'stockData': results}), 200

    except Exception as e:
        print(f"Backend UNHANDLED ERROR: An unhandled backend error occurred: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)