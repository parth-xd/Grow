import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()
db_url = os.getenv('DB_URL')

if db_url:
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        # Check what's actually in the database
        cursor.execute('''
            SELECT symbol, MAX(close) as latest_price, MIN(close) as min_price, 
                   AVG(close) as avg_price, COUNT(*) as total_candles
            FROM stock_prices 
            GROUP BY symbol
        ''')
        rows = cursor.fetchall()
        
        print('Stock prices in database:')
        for symbol, latest, min_p, avg_p, count in rows:
            print(f'\n  {symbol}:')
            print(f'    Latest: ₹{latest:.2f}')
            print(f'    Min: ₹{min_p:.2f}')
            print(f'    Avg: ₹{avg_p:.2f}')
            print(f'    Total candles: {count}')
        
        cursor.close()
        conn.close()
    except Exception as e:
        print(f'Error: {e}')
else:
    print('No DB_URL configured')
