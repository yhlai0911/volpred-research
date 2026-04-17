import { NextRequest, NextResponse } from 'next/server';
import { getQuestions } from '@/lib/data-server';
import { createServiceClient } from '@/lib/supabase-server';
import { createClient } from '@supabase/supabase-js';

export async function GET() {
  try {
    const questions = await getQuestions('user');
    return NextResponse.json(questions);
  } catch {
    return NextResponse.json([]);
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const question = body.question?.trim();
    if (!question || question.length < 10) {
      return NextResponse.json(
        { error: '問題至少需要 10 個字' },
        { status: 400 }
      );
    }

    // Verify auth: extract token from Authorization header or cookie
    const authHeader = request.headers.get('authorization');
    const token = authHeader?.replace('Bearer ', '');

    let userId: string | null = null;
    let userEmail: string | null = null;

    if (token) {
      const supabaseAuth = createClient(
        process.env.NEXT_PUBLIC_SUPABASE_URL!,
        process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
      );
      const { data: { user } } = await supabaseAuth.auth.getUser(token);
      if (user) {
        userId = user.id;
        userEmail = user.email || null;
      }
    }

    if (!userId) {
      return NextResponse.json(
        { error: '請先登入再提問' },
        { status: 401 }
      );
    }

    // Check per-user monthly quota
    const supabase = createServiceClient();
    const now = new Date();
    const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).toISOString();

    const { count } = await supabase
      .from('questions')
      .select('id', { count: 'exact', head: true })
      .eq('user_id', userId)
      .eq('source', 'user')
      .gte('created_at', monthStart);

    const FREE_QUOTA = 3;
    if ((count || 0) >= FREE_QUOTA) {
      // Check if user is premium (unlimited)
      const { data: profile } = await supabase
        .from('profiles')
        .select('role')
        .eq('id', userId)
        .single();

      if (!profile || (profile.role !== 'premium' && profile.role !== 'admin')) {
        return NextResponse.json(
          { error: `本月配額已用完（${FREE_QUOTA}/${FREE_QUOTA}）` },
          { status: 429 }
        );
      }
    }

    // Insert question with user_id
    const { data, error } = await supabase
      .from('questions')
      .insert({
        source: 'user',
        user_id: userId,
        question,
        status: 'evaluating',
        proposer: userEmail?.split('@')[0] || '會員',
      })
      .select('id')
      .single();

    if (error) throw error;
    return NextResponse.json({ success: true, id: data.id });
  } catch (e: any) {
    if (e?.message?.includes('quota')) {
      return NextResponse.json({ error: e.message }, { status: 429 });
    }
    return NextResponse.json({ error: 'Failed to save' }, { status: 500 });
  }
}
