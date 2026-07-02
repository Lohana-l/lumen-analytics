-- Aucun timestamp d'événement ne peut être dans le futur par rapport à reporting_date.
select event_id, event_ts
from {{ ref('stg_events') }}
where event_ts > '{{ var("reporting_date") }}'::timestamptz
