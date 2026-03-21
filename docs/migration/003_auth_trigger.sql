-- ═══════════════════════════════════════════════════════════
-- VolPred v2 — Auth Trigger
-- 新用戶註冊時自動建立 profile
-- ═══════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION handle_new_user() RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.profiles (id, email, display_name, avatar_url)
  VALUES (
    NEW.id,
    NEW.email,
    COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.raw_user_meta_data->>'name', split_part(NEW.email, '@', 1)),
    NEW.raw_user_meta_data->>'avatar_url'
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION handle_new_user();

-- ═══════════════════════════════════════════════════════════
-- 用戶提問時自動檢查配額
-- ═══════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION check_question_quota() RETURNS TRIGGER AS $$
DECLARE
  current_period DATE;
  usage_record quota_usage%ROWTYPE;
  user_role TEXT;
BEGIN
  -- 只檢查用戶提問
  IF NEW.source != 'user' THEN
    RETURN NEW;
  END IF;

  current_period := date_trunc('month', NOW())::date;

  -- 取得用戶角色
  SELECT role INTO user_role FROM profiles WHERE id = NEW.user_id;

  -- premium 不限制
  IF user_role = 'premium' OR user_role = 'admin' THEN
    RETURN NEW;
  END IF;

  -- 取得或建立當月配額記錄
  INSERT INTO quota_usage (user_id, period_start)
  VALUES (NEW.user_id, current_period)
  ON CONFLICT (user_id, period_start) DO NOTHING;

  SELECT * INTO usage_record FROM quota_usage
  WHERE user_id = NEW.user_id AND period_start = current_period;

  -- 檢查是否超額
  IF usage_record.questions_used >= usage_record.questions_limit THEN
    RAISE EXCEPTION 'Monthly question quota exceeded (% / %)',
      usage_record.questions_used, usage_record.questions_limit;
  END IF;

  -- 增加使用量
  UPDATE quota_usage
  SET questions_used = questions_used + 1
  WHERE user_id = NEW.user_id AND period_start = current_period;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER check_quota_before_question
  BEFORE INSERT ON questions
  FOR EACH ROW EXECUTE FUNCTION check_question_quota();
