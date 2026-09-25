import psycopg, os
from dotenv import load_dotenv
load_dotenv()
c = psycopg.connect(os.getenv("DATABASE_URL_ADMIN"))
cur = c.cursor()
for v in ("0001", "0002", "0003", "0004", "0005", "0006", "0007", "0008"):
    cur.execute("INSERT INTO schema_migrations (version) VALUES (%s) ON CONFLICT DO NOTHING", (v,))
c.commit()
c.close()
print("Listo")
