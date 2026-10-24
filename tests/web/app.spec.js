import { test, expect } from '@playwright/test';

async function ready(page) {
  await page.goto('./');
  await expect(page.getByRole('button', { name: '길이 보기' })).toBeEnabled();
}

test('hints stay hidden until requested and reset on rank changes', async ({ page }) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await ready(page);
  await expect(page.locator('body')).not.toContainText('사과');
  await page.getByRole('button', { name: '길이 보기' }).click();
  await expect(page.locator('#value-length')).toHaveText('2글자');
  await page.getByRole('button', { name: '초성 보기' }).click();
  await expect(page.locator('#value-initial_consonant')).toHaveText('ㅅㄱ');
  await page.locator('#rank').fill('1000');
  await expect(page.locator('#value-length')).toHaveText('아직 열지 않은 힌트');
  await expect(page.locator('#target')).toContainText('1000위');
  await page.locator('#rank').fill('1001');
  await expect(page.locator('#rank-error')).toBeVisible();
  await expect(page.getByRole('button', { name: '품사 보기' })).toBeDisabled();
  expect(errors).toEqual([]);
});

test('whole word requires confirmation, cancel hides it, changing round closes it', async ({ page }) => {
  await ready(page);
  await page.getByRole('button', { name: '전체 단어 보기' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', { name: '더 생각해볼게요' }).click();
  await expect(page.locator('body')).not.toContainText('사과');
  await page.getByRole('button', { name: '전체 단어 보기' }).click();
  await page.getByRole('button', { name: '단어 공개하기' }).click();
  await expect(page.locator('#value-word')).toHaveText('사과');
  const values = await page.locator('#round option').evaluateAll(options => options.map(option => option.value));
  await page.locator('#round').selectOption(values[1]);
  await expect(page.locator('#value-word')).toHaveText('아직 열지 않은 힌트');
});

test('single characters use one-based code point positions', async ({ page }) => {
  await ready(page);
  await page.locator('#rank').fill('5');
  await page.locator('#character').fill('2');
  await page.getByRole('button', { name: '한 글자 보기' }).click();
  await expect(page.locator('#value-character')).toHaveText('2번째 글자 · 😀');
  await page.locator('#character').fill('4');
  await page.getByRole('button', { name: '한 글자 보기' }).click();
  await expect(page.locator('#value-character')).toContainText('1~3');
});

test('manifest failure provides retry and recovers', async ({ page }) => {
  await page.route('**/data/manifest.json', route => route.fulfill({ status: 503, body: '{}' }));
  await page.goto('./');
  await expect(page.locator('#load-error')).toBeVisible();
  await expect(page.getByRole('button', { name: '길이 보기' })).toBeDisabled();
  await page.unroute('**/data/manifest.json');
  await page.getByRole('button', { name: '다시 불러오기' }).click();
  await expect(page.getByRole('button', { name: '길이 보기' })).toBeEnabled();
});

test('a late previous response cannot replace the selected round', async ({ page }) => {
  await ready(page);
  const values = await page.locator('#round option').evaluateAll(options => options.map(option => option.value));
  await page.route(`**/rounds/${values[1]}.*.json`, async route => {
    await new Promise(resolve => setTimeout(resolve, 400));
    await route.continue().catch(() => {});
  });
  await page.locator('#round').selectOption(values[1]);
  await page.locator('#round').selectOption(values[2]);
  await expect(page.locator('#target')).toContainText(`${values[2]}회`);
  await page.waitForTimeout(500);
  await expect(page.locator('#target')).toContainText(`${values[2]}회`);
});

test('mobile layout fits viewport and keyboard can reach hints', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await ready(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: '길이 보기' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#value-length')).toHaveText('2글자');
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: 'test-results/mobile.png', fullPage: true });
});

test('missing today shows the actual archived date and keeps past rounds usable', async ({ page }) => {
  await page.route('**/data/manifest.json', async route => {
    const response = await route.fetch();
    const data = await response.json();
    data.rounds.pop(); data.latest_round = data.rounds.at(-1).round;
    await route.fulfill({ json: data });
  });
  await ready(page);
  await expect(page.locator('#notice')).toContainText('갱신 대기');
  await page.getByRole('button', { name: '품사 보기' }).click();
  await expect(page.locator('#value-pos')).toHaveText('명사');
});

test('an empty archive explains the state and keeps reveal buttons disabled', async ({ page }) => {
  await page.route('**/data/manifest.json', route => route.fulfill({ json: {
    schema_version: 1, timezone: 'Asia/Seoul', latest_round: null, rounds: [],
  } }));
  await page.goto('./');
  await expect(page.locator('#target')).toHaveText('보관된 회차가 없어요');
  await expect(page.getByRole('button', { name: '길이 보기' })).toBeDisabled();
  await expect(page.getByRole('button', { name: '다시 불러오기' })).toBeVisible();
});
