DO $$
DECLARE
    relation record;
    violation boolean;
BEGIN
    FOR relation IN
        SELECT constraint_row.conname,
               constraint_row.conrelid::regclass AS child_table,
               constraint_row.confrelid::regclass AS parent_table,
               string_agg(
                   format('child.%I = parent.%I', child_column.attname, parent_column.attname),
                   ' AND ' ORDER BY key_column.ordinality
               ) AS join_predicate,
               string_agg(
                   format('child.%I IS NOT NULL', child_column.attname),
                   ' AND ' ORDER BY key_column.ordinality
               ) AS child_present_predicate,
               (array_agg(
                   format('parent.%I IS NULL', parent_column.attname)
                   ORDER BY key_column.ordinality
               ))[1] AS parent_missing_predicate
        FROM pg_constraint AS constraint_row
        JOIN LATERAL unnest(constraint_row.conkey, constraint_row.confkey)
             WITH ORDINALITY AS key_column(child_number, parent_number, ordinality)
             ON true
        JOIN pg_attribute AS child_column
          ON child_column.attrelid = constraint_row.conrelid
         AND child_column.attnum = key_column.child_number
        JOIN pg_attribute AS parent_column
          ON parent_column.attrelid = constraint_row.confrelid
         AND parent_column.attnum = key_column.parent_number
        WHERE constraint_row.contype = 'f'
          AND constraint_row.connamespace = 'public'::regnamespace
        GROUP BY constraint_row.oid
    LOOP
        EXECUTE format(
            'SELECT EXISTS ('
            'SELECT 1 FROM %s AS child LEFT JOIN %s AS parent ON %s '
            'WHERE %s AND %s)',
            relation.child_table,
            relation.parent_table,
            relation.join_predicate,
            relation.child_present_predicate,
            relation.parent_missing_predicate
        ) INTO violation;
        IF violation THEN
            RAISE EXCEPTION 'foreign key integrity violation: % on % -> %',
                relation.conname, relation.child_table, relation.parent_table;
        END IF;
    END LOOP;
END
$$;
