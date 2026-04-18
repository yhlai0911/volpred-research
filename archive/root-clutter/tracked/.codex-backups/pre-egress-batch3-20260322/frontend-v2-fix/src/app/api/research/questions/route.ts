import { NextResponse } from 'next/server';
import { getQuestions } from '@/lib/data-server';

export async function GET() {
  try {
    const data = await getQuestions('internal');
    return NextResponse.json(data);
  } catch {
    return NextResponse.json([]);
  }
}
