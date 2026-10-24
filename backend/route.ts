import { handleGuess } from '@/lib/scoring';

export const dynamic = 'force-dynamic';
function handle(request: Request) {
  const cache = (globalThis as typeof globalThis & { caches?: { default?: Cache } }).caches?.default;
  return handleGuess(request, { cache });
}
export const POST = handle;
export const OPTIONS = handle;
