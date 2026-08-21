-- EN: OMX preparation is a persisted arm step that runs in parallel with Pinky navigation.
-- KO: OMX 준비는 Pinky 이동과 병렬 실행되는 영속 arm step이다.
ALTER TABLE job_steps
  DROP CHECK chk_job_steps_action,
  ADD CONSTRAINT chk_job_steps_action CHECK (action_type IN
    ('navigate','dock','inspect','prepare','pick','load','unload','place','verify',
     'handover','wait','recover','return_home','safety_stop'));
