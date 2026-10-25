import { test, expect } from '@playwright/test';
import { GUESS_API_URL } from '../../web/config.js';

async function ready(page) {
  await page.goto('./');
  await expect(page.locator('#guess-word')).toBeEnabled();
}
async function guess(page, word) {
  await page.locator('#guess-word').fill(word);
  await page.getByRole('button', { name: '추측하기 →' }).click();
}

test('cached guesses, duplicates and per-round records survive reload', async ({ page }) => {
  await ready(page);
  await guess(page, '과일');
  await expect(page.locator('#game-count')).toHaveText('1번 추측');
  await expect(page.locator('#guess-rows')).toContainText('과일');
  await guess(page, '과일');
  await expect(page.locator('#game-message')).toContainText('이미 입력한');
  await expect(page.locator('#game-count')).toHaveText('1번 추측');
  await page.reload();
  await expect(page.locator('#game-count')).toHaveText('1번 추측');
  const values = await page.locator('#round option').evaluateAll(options => options.map(option => option.value));
  await page.locator('#round').selectOption(values[1]);
  await expect(page.locator('#game-count')).toHaveText('0번 추측');
  await page.locator('#round').selectOption(values[0]);
  await expect(page.locator('#game-count')).toHaveText('1번 추측');
});

test('previous cached scores are repaired on reload without losing history', async ({ page }) => {
  await ready(page);
  await guess(page, '과일');
  const original = await page.locator('#guess-rows tr td').nth(2).innerText();
  await page.evaluate(() => {
    const key = `komantle-helper:game:v1:${document.getElementById('round').value}`;
    const saved = JSON.parse(localStorage.getItem(key));
    saved.guesses[0].similarity /= 100;
    localStorage.setItem(key, JSON.stringify(saved));
  });
  await page.reload();
  await expect(page.locator('#game-count')).toHaveText('1번 추측');
  await expect(page.locator('#guess-rows tr td').nth(2)).toHaveText(original);
  await page.reload();
  await expect(page.locator('#guess-rows tr td').nth(2)).toHaveText(original);
});

test('correct answer ends the game and restores completed state', async ({ page }) => {
  await ready(page); await guess(page, '사과');
  await expect(page.locator('#game-message')).toContainText('정답이에요');
  await expect(page.locator('#guess-word')).toBeDisabled();
  await page.reload();
  await expect(page.locator('#game-message')).toContainText('1번 만에');
  await expect(page.locator('#guess-word')).toBeDisabled();
});

test('giveup requires confirmation and is kept on reload', async ({ page }) => {
  await ready(page);
  await page.locator('#give-up').click();
  await page.getByRole('dialog').getByRole('button', { name: '계속 풀어볼게요' }).click();
  await expect(page.locator('#game-message')).not.toContainText('사과');
  await page.locator('#give-up').click();
  await page.getByRole('dialog').getByRole('button', { name: '정답 보고 포기하기' }).click();
  await expect(page.locator('#game-message')).toContainText('사과');
  await page.reload();
  await expect(page.locator('#game-message')).toContainText('이번 회차를 마쳤어요');
});

test('uncached words are scored through the API and failed words do not count', async ({ page }) => {
  await page.route(GUESS_API_URL, async route => {
    const headers = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'POST, OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type' };
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
    const { word } = route.request().postDataJSON();
    return route.fulfill(word === '바다'
      ? { headers, json: { word, similarity: 12.5, rank: null, correct: false } }
      : { headers, status: 404, json: { error: '원본 사전에 없는 단어예요.' } });
  });
  await ready(page); await guess(page, '바다');
  await expect(page.locator('#guess-rows')).toContainText('12.50');
  await guess(page, '없는테스트단어');
  await expect(page.locator('#game-message')).toContainText('사전에 없는');
  await expect(page.locator('#game-count')).toHaveText('1번 추측');
});

test('changing rounds while a guess is pending discards its response', async ({ page }) => {
  let resolveRequest;
  await page.route(GUESS_API_URL, async route => {
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'POST', 'Access-Control-Allow-Headers': 'Content-Type' } });
    await new Promise(resolve => { resolveRequest = resolve; });
    await route.fulfill({ headers: { 'Access-Control-Allow-Origin': '*' }, json: { word: '바다', similarity: 12, rank: null, correct: false } }).catch(() => {});
  });
  await ready(page); await guess(page, '바다');
  await expect.poll(() => Boolean(resolveRequest)).toBe(true);
  const values = await page.locator('#round option').evaluateAll(options => options.map(option => option.value));
  await page.locator('#round').selectOption(values[1]);
  resolveRequest();
  await expect(page.locator('#guess-word')).toBeEnabled();
  await expect(page.locator('#game-count')).toHaveText('0번 추측');
  await page.locator('#round').selectOption(values[0]);
  await expect(page.locator('#game-count')).toHaveText('0번 추측');
});

test('game fits a narrow mobile screen and submits with the keyboard', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await ready(page);
  await page.locator('#guess-word').fill('과일');
  await page.locator('#guess-word').press('Enter');
  await expect(page.locator('#game-count')).toHaveText('1번 추측');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('round deletion requires confirmation, preserves other rounds and stays deleted after reload', async ({ page }) => {
  await ready(page);
  const values = await page.locator('#round option').evaluateAll(options => options.map(option => option.value));
  await guess(page, '과일');
  await page.locator('#round').selectOption(values[1]);
  await expect(page.locator('#guess-word')).toBeEnabled();
  await guess(page, '과일');
  await page.locator('#round').selectOption(values[0]);
  await expect(page.locator('#game-count')).toHaveText('1번 추측');
  await page.getByRole('button', { name: '이 회차 기록 삭제', exact: true }).click();
  await expect(page.locator('#delete-records-title')).toContainText(`${values[0]}회`);
  await page.getByRole('button', { name: '취소', exact: true }).click();
  await expect(page.locator('#game-count')).toHaveText('1번 추측');
  await page.getByRole('button', { name: '이 회차 기록 삭제', exact: true }).click();
  await page.getByRole('button', { name: '기록 삭제하기', exact: true }).click();
  await expect(page.locator('#game-count')).toHaveText('0번 추측');
  await expect(page.locator('#game-history')).toBeHidden();
  await expect(page.locator('#game-message')).toContainText('이 회차 기록을 삭제했어요');
  expect(await page.evaluate(round => localStorage.getItem(`komantle-helper:game:v1:${round}`), values[0])).toBeNull();
  await page.reload();
  await expect(page.locator('#guess-word')).toBeEnabled();
  await expect(page.locator('#game-count')).toHaveText('0번 추측');
  await page.locator('#round').selectOption(values[1]);
  await expect(page.locator('#game-count')).toHaveText('1번 추측');
});

test('all-round deletion removes every saved game and preserves unrelated storage', async ({ page }) => {
  await ready(page);
  await guess(page, '과일');
  await page.evaluate(() => {
    const currentKey = `komantle-helper:game:v1:${document.getElementById('round').value}`;
    localStorage.setItem('komantle-helper:game:v1:1', localStorage.getItem(currentKey));
    localStorage.setItem('komantle-helper:game:v1:2', '{broken record');
    localStorage.setItem('other-app:preference', 'keep');
  });
  await page.getByRole('button', { name: '전체 회차 기록 삭제', exact: true }).click();
  await page.keyboard.press('Escape');
  await expect(page.locator('#game-count')).toHaveText('1번 추측');
  await page.getByRole('button', { name: '전체 회차 기록 삭제', exact: true }).click();
  await page.getByRole('button', { name: '기록 삭제하기', exact: true }).click();
  await expect(page.locator('#game-count')).toHaveText('0번 추측');
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual(['other-app:preference']);
  await page.reload();
  await expect(page.locator('#guess-word')).toBeEnabled();
  await expect(page.locator('#game-count')).toHaveText('0번 추측');
});

for (const end of ['win', 'giveup']) {
  test(`deletion resets ${end} state and permits playing again`, async ({ page }) => {
    await ready(page);
    if (end === 'win') await guess(page, '사과');
    else {
      await page.locator('#give-up').click();
      await page.locator('#give-up-dialog').getByRole('button', { name: '정답 보고 포기하기' }).click();
    }
    await expect(page.locator('#guess-word')).toBeDisabled();
    await page.getByRole('button', { name: '이 회차 기록 삭제', exact: true }).click();
    await page.getByRole('button', { name: '기록 삭제하기', exact: true }).click();
    await expect(page.locator('#guess-word')).toBeEnabled();
    await expect(page.locator('#game-message')).not.toContainText('사과');
    await guess(page, '과일');
    await expect(page.locator('#game-count')).toHaveText('1번 추측');
  });
}

test('deletion during scoring discards the response instead of restoring deleted history', async ({ page }) => {
  let resolveRequest;
  await page.route(GUESS_API_URL, async route => {
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'POST', 'Access-Control-Allow-Headers': 'Content-Type' } });
    await new Promise(resolve => { resolveRequest = resolve; });
    await route.fulfill({ headers: { 'Access-Control-Allow-Origin': '*' }, json: { word: '바다', similarity: 12, rank: null, correct: false } }).catch(() => {});
  });
  await ready(page); await guess(page, '과일'); await guess(page, '바다');
  await expect.poll(() => Boolean(resolveRequest)).toBe(true);
  await page.getByRole('button', { name: '이 회차 기록 삭제', exact: true }).click();
  await page.getByRole('button', { name: '기록 삭제하기', exact: true }).click();
  await expect(page.locator('#guess-word')).toBeEnabled();
  resolveRequest();
  await page.reload();
  await expect(page.locator('#guess-word')).toBeEnabled();
  await expect(page.locator('#game-count')).toHaveText('0번 추측');
});

test('failed storage deletion keeps the current game and explains the failure', async ({ page }) => {
  await ready(page); await guess(page, '과일');
  await page.evaluate(() => { Storage.prototype.removeItem = () => { throw new Error('denied'); }; });
  await page.getByRole('button', { name: '이 회차 기록 삭제', exact: true }).click();
  await page.getByRole('button', { name: '기록 삭제하기', exact: true }).click();
  await expect(page.locator('#game-message')).toContainText('기록을 삭제하지 못했어요');
  await expect(page.locator('#game-count')).toHaveText('1번 추측');
  await page.reload();
  await expect(page.locator('#game-count')).toHaveText('1번 추측');
});
