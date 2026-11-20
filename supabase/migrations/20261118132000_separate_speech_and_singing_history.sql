ALTER TABLE public.sonivox_generations
  ADD COLUMN IF NOT EXISTS generation_type text NOT NULL DEFAULT 'speech';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'sonivox_generations_generation_type_check'
      AND conrelid = 'public.sonivox_generations'::regclass
  ) THEN
    ALTER TABLE public.sonivox_generations
      ADD CONSTRAINT sonivox_generations_generation_type_check
      CHECK (generation_type IN ('speech', 'singing'));
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS sonivox_generations_user_type_created_idx
  ON public.sonivox_generations (user_id, generation_type, created_at DESC);

NOTIFY pgrst, 'reload schema';
