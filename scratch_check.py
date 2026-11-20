from applypilot.database import init_db, get_connection
init_db()
conn = get_connection()
result3 = conn.execute('SELECT MIN(discovered_at), MAX(discovered_at) FROM jobs').fetchone()
print('Date range: min=%s  max=%s' % (result3[0], result3[1]))
result4 = conn.execute("SELECT apply_status, COUNT(*) FROM jobs GROUP BY apply_status ORDER BY COUNT(*) DESC").fetchall()
for r in result4:
    print('  status=%r count=%d' % (r[0], r[1]))
