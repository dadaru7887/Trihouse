# Database ER Diagram Design

## Goal

Rewrite `docs/database/schema_diagram.drawio` as a readable, two-page ER diagram derived from `db/schema_mysql.sql`. The diagram must show both the `trihouse_fms` and `trihouse_recovery` schemas without relationship lines crossing table contents.

## Deliverable

The draw.io file contains two pages:

1. **01 Summary ERD** — all tables, primary/foreign/unique keys, and only the domain columns needed to understand each entity.
2. **02 Detailed ERD** — all columns in DDL order, SQL types, nullability, and PK/FK/UK markers.

Both pages use the same table grouping and relationship directions so readers can switch pages without relearning the layout.

## Source of Truth and Scope

- Use the current working-tree version of `db/schema_mysql.sql` as the source of truth.
- Include all tables created in the `trihouse_fms` and `trihouse_recovery` sections.
- Render declared MySQL foreign keys as solid Crow's Foot relationships.
- Render cross-schema identifier references that have no declared FK as dashed logical relationships and label them as logical references.
- Do not include the separate `control_system/db/schema.sql` schema.

## Visual Structure

- Group related tables into spatial domains: master/location data, jobs and execution, inventory, telemetry/integration, incidents/audit/artifacts, and recovery.
- Use blue table headers for `trihouse_fms` and green table headers for `trihouse_recovery`, with neutral white column bodies.
- Put a compact legend and page title outside the relationship routing area.
- Use a wide landscape canvas with enough whitespace for edge corridors between rows and columns.

## Table Notation

- Header: fully qualified `schema.table` name.
- Column rows: key marker, column name, type; the detailed page also marks nullable columns.
- Composite unique keys are identified by constraint name so individual `UK` markers are not mistaken for independent uniqueness.
- Primary keys appear first visually only when that does not conflict with preserving DDL order; otherwise their row markers make them immediately visible.

## Relationship and Arrow Safety

- Use orthogonal connectors with fixed connection points on the relevant sides of each table.
- Route connectors only through dedicated whitespace corridors; no connector segment may pass through a table rectangle or its text.
- Separate parallel relationships with distinct waypoints. This is required for repeated relationships such as source/destination locations and incident worker roles.
- Use Crow's Foot endpoints for cardinality and optionality inferred from FK nullability and uniqueness.
- Place relationship labels in corridor whitespace, offset from bends and endpoints.
- Enable line jumps where crossings remain unavoidable.
- Use dashed strokes only for logical, non-enforced cross-schema references.

## Validation

- Parse the final XML to confirm it is well formed and contains both expected page names.
- Compare rendered table and physical-FK counts with the DDL.
- Inspect connector geometry to ensure every connector has explicit routing and no relationship is a default center-to-center line.
- If a draw.io renderer is available locally, export or render both pages for a final visual collision check; otherwise validate geometry bounds programmatically.

## Non-goals

- Changing the database schema or constraints.
- Documenting the legacy/control-system schema.
- Adding inferred business relationships that are not represented by identifiers in the DDL.
