import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DB_URL")

if DB_URL:
    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor()
    
    # Check record counts per symbol
    cursor.execute("SELECT symbol, COUNT(*) as count FROM stock_prices GROUP BY symbol")
    results = cursor.fetchall()
    
    print("Records per symbol:")
    for symbol, count in results:
        print(f"  {symbol}: {count} records")
    
    # Show sample of latest prices
    print("\nLatest prices by symbol:")
    cursor.execute("""
        SELECT symbol, date, close, volume 
        FROM stock_prices 
        ORDER BY symbol, date DESC 
        LIMIT 9
    """)
    for row in cursor.fetchall():
        print(f"  {row[0]:12} {row[1]} Close: ₹{row[2]:.2f} Vol: {row[3]}")
    
    cursor.close()
    conn.close()
