const { test, expect } = require('@playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');

const fixtures = process.env.QC_TOOL_BROWSER_FIXTURES;

async function selectFile(page, selection, filename) {
  const picker = page.locator('[data-upload-picker]');
  await expect(picker.locator('[data-upload-browse]')).toBeVisible();
  const filePath = path.join(fixtures, filename);
  if (selection === 'chooser') {
    // Click the actual enhanced button. Directly setting the hidden input would
    // miss the Firefox regression where that button did not stage native files.
    const chooser = page.waitForEvent('filechooser');
    await picker.locator('[data-upload-browse]').click();
    await (await chooser).setFiles(filePath);
  } else {
    const bytes = await fs.readFile(filePath);
    // Exercise native File/DataTransfer objects and the real drop handler in
    // each browser. OS drag gestures cannot be automated portably in headless CI.
    const transfer = await page.evaluateHandle(({ filename, bytes }) => {
      const transfer = new DataTransfer();
      transfer.items.add(new File([new Uint8Array(bytes)], filename, {
        type: filename.endsWith('.json') ? 'application/json' : 'application/zip',
      }));
      return transfer;
    }, { filename, bytes: [...bytes] });
    await picker.dispatchEvent('drop', { dataTransfer: transfer });
    await transfer.dispose();
  }
  const row = page.locator('[data-upload-list] > li').filter({ hasText: filename });
  await expect(row).toHaveCount(1);
  await expect(row).toHaveAttribute('data-state', 'selected');
  return row;
}

test.beforeEach(async ({ page }) => {
  await page.goto('/accounts/login/');
  await page.getByLabel('Username', { exact: true }).fill('browser-admin');
  await page.getByLabel('Password', { exact: true }).fill('disposable-browser-test-password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).not.toHaveURL(/\/accounts\/login\//);
});

for (const selection of ['chooser', 'drop']) {
  test(`${selection}: specification, delivery and boundary uploads persist`, async ({ page }, testInfo) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const ident = `ci_smoke_${testInfo.project.name}_${selection}`;

    await page.goto('/products/upload/');
    const specification = await selectFile(page, selection, `${ident}.json`);
    await specification.getByRole('button', { name: `Add: ${ident}.json`, exact: true }).click();
    await expect(specification).toHaveAttribute('data-state', 'completed');
    await specification.getByRole('link', { name: 'View product' }).click();
    await page.reload();
    await expect(page).toHaveURL(new RegExp(`/products/${ident}/`));

    const deliveryName = `${ident}_CZ.zip`;
    await page.goto('/deliveries/upload/');
    const delivery = await selectFile(page, selection, deliveryName);
    await delivery.getByRole('button', { name: `Upload: ${deliveryName}`, exact: true }).click();
    await expect(delivery).toHaveAttribute('data-state', 'completed');
    await delivery.getByRole('link', { name: 'View delivery' }).click();
    await page.reload();
    await expect(page.locator('#job-history-delivery')).toContainText(deliveryName);

    await page.goto('/admin/boundaries/upload/');
    const boundary = await selectFile(page, selection, 'boundaries.zip');
    await page.getByRole('button', { name: 'Upload and activate', exact: true }).click();
    await expect(boundary).toHaveAttribute('data-state', 'completed');
    await page.reload();
    const catalog = await page.request.get('/admin/boundaries/data/raster/');
    expect(catalog.ok()).toBeTruthy();
    expect(await catalog.json()).toEqual(expect.arrayContaining([
      expect.objectContaining({ filename: 'smoke.tif' }),
    ]));
    expect(errors).toEqual([]);
  });
}
