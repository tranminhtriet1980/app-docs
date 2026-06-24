import sqlite3

c = sqlite3.connect("immigration.db")
rows = c.execute(
    """
    SELECT a.display_name, d.original_filename, ef.field_key, ef.field_value
    FROM applicants a
    JOIN documents d ON d.applicant_id = a.id
    JOIN extracted_fields ef ON ef.document_id = d.id
    WHERE ef.field_key IN ('birth_city', 'city_of_birth', 'place_of_birth', 'birth_place')
      AND COALESCE(ef.field_value, '') <> ''
    ORDER BY a.display_name, d.original_filename
    """
).fetchall()
with open('_birth_extract_out.txt', 'w', encoding='utf-8') as f:
    for r in rows:
        f.write(repr(r) + '\n')
