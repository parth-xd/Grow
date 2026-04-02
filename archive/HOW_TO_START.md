# How to Start the Groww AI Trading Bot

## 3 SIMPLE STEPS

---

### STEP 1: Open Terminal
Press this key combination in VS Code:

**Ctrl + Backtick**

(That's the ` key, usually below the Esc key)

---

### STEP 2: Type this EXACTLY in terminal:

```
cd /Users/parthsharma/Desktop/Grow
```

Then press **ENTER**

---

### STEP 3: Type this EXACTLY in terminal:

```
python3 app.py
```

Then press **ENTER**

---

### STEP 4: Wait for this message in terminal:

Look for this text in your terminal:

```
Running on http://127.0.0.1:8000
```

---

### STEP 5: Open your browser

Type this in your browser address bar:

```
http://127.0.0.1:8000
```

Then press **ENTER**

---

## DONE!

Your dashboard is now running. You should see the Groww trading bot dashboard.

---

## TO STOP THE SERVER

Press **Ctrl + C** in your terminal

---

## IF YOU GET AN ERROR

**Error: "Port 8000 already in use"**

Type this in terminal:
```
kill -9 $(lsof -t -i:8000)
```

Then run Step 3 again: `python3 app.py`

---

**That's it! Simple as that.**
