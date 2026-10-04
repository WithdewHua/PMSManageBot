/* eslint-env node */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')
const { parse } = require('@vue/compiler-sfc')

const root = path.resolve(__dirname, '..')
const stats = () => ({
  initialized: true, week_start_ms: 1, week_end_ms: 2,
  global_used: 24, global_limit: 30, personal_limit: 5,
  historical_issued: 24, new_issued: 0,
  global_blocked_count: 0, personal_blocked_count: 0, both_blocked_count: 0,
  first_exhausted_at_ms: null, users: [{ tg_id: 1, issued: 4 }], sources: [],
})

function instance(overrides = {}) {
  const file = fs.readFileSync(path.join(root, 'src/components/WheelInviteQuotaPanel.vue'), 'utf8')
  const parsed = parse(file)
  assert.deepEqual(parsed.errors, [])
  const source = parsed.descriptor.script.content.replace(/^import .*$/gm, '').replace('export default', 'module.exports =')
  const services = {
    getLuckyWheelInviteQuotas: async () => ({ data: { global_weekly_limit: 30, personal_weekly_limit: 5 } }),
    getLuckyWheelInviteQuotaStats: async () => ({ data: stats() }),
    updateLuckyWheelInviteQuotas: async value => ({ data: value }),
    ...overrides,
  }
  const context = { module: { exports: {} }, Intl, Date, ...services }
  vm.runInNewContext(source, context)
  const options = context.module.exports
  const state = options.data()
  for (const [name, method] of Object.entries(options.methods)) state[name] = method.bind(state)
  for (const [name, get] of Object.entries(options.computed)) Object.defineProperty(state, name, { get: get.bind(state) })
  return state
}

test('successful load preserves actual accounting and allows zero limit', async () => {
  const state = instance()
  assert.equal(state.canSave, false)
  await state.load()
  assert.equal(state.stats.global_used, 24)
  assert.equal(state.canSave, true)
  state.limits.global_weekly_limit = 0
  assert.equal(state.canSave, true)
  await state.save()
  assert.equal(state.limits.global_weekly_limit, 0)
  assert.match(state.notice, /已保存/)
  assert.equal(state.error, '')
})

test('invalid limits cannot be saved', async () => {
  let writes = 0
  const state = instance({ updateLuckyWheelInviteQuotas: async () => { writes++; throw new Error('unexpected') } })
  await state.load()
  for (const value of [-1, 1.5, true, '', '5', null, NaN, Infinity, 2147483648]) {
    state.limits.personal_weekly_limit = value
    assert.equal(state.canSave, false)
    await state.save()
  }
  assert.equal(writes, 0)
})

test('initial read failure does not present zero as valid accounting', async () => {
  const state = instance({ getLuckyWheelInviteQuotaStats: async () => { throw new Error('offline') } })
  await state.load()
  assert.equal(state.loaded, false)
  assert.equal(state.stats, null)
  assert.equal(state.limits.global_weekly_limit, null)
  assert.equal(state.limits.personal_weekly_limit, null)
  assert.equal(state.canSave, false)
  assert.match(state.error, /请求失败/)
})

test('malformed read is not accepted as a usable snapshot', async () => {
  const state = instance({ getLuckyWheelInviteQuotaStats: async () => ({ data: {} }) })
  await state.load()
  assert.equal(state.loaded, false)
  assert.equal(state.stats, null)
})

test('refresh failure retains previous data and warns that it is stale', async () => {
  let calls = 0
  const state = instance({ getLuckyWheelInviteQuotaStats: async () => {
    if (calls++) throw new Error('offline')
    return { data: stats() }
  } })
  await state.load()
  await state.load()
  assert.equal(state.stats.global_used, 24)
  assert.match(state.error, /上次加载/)
})

test('failed save never reports success', async () => {
  const state = instance({ updateLuckyWheelInviteQuotas: async () => { throw new Error('offline') } })
  await state.load()
  await state.save()
  assert.equal(state.notice, '')
  assert.match(state.error, /保存失败/)
  assert.equal(state.stats.global_used, 24)
  assert.equal(state.saving, false)
})

test('saved configuration and failed statistics refresh are distinguished', async () => {
  let calls = 0
  const state = instance({ getLuckyWheelInviteQuotaStats: async () => {
    if (calls++) throw new Error('offline')
    return { data: stats() }
  } })
  await state.load()
  await state.save()
  assert.match(state.notice, /已保存/)
  assert.match(state.error, /统计刷新失败/)
  assert.equal(state.stats.global_used, 24)
})

test('management and public helpers use distinct HTTP routes', async () => {
  const calls = []
  const client = {
    get: async (...args) => calls.push(['get', ...args]),
    put: async (...args) => calls.push(['put', ...args]),
  }
  const raw = fs.readFileSync(path.join(root, 'src/services/wheelService.js'), 'utf8')
  const source = raw.replace(/^import .*$/gm, '').replace(/^export const /gm, 'const ') +
    '\nmodule.exports = {getLuckyWheelConfig,getAdminLuckyWheelConfig,getLuckyWheelInviteQuotas,updateLuckyWheelInviteQuotas,getLuckyWheelInviteQuotaStats}'
  const context = { module: { exports: {} }, apiClient: client }
  vm.runInNewContext(source, context)
  const api = context.module.exports
  await api.getLuckyWheelConfig()
  await api.getAdminLuckyWheelConfig()
  await api.getLuckyWheelInviteQuotas()
  await api.updateLuckyWheelInviteQuotas({ global_weekly_limit: 0, personal_weekly_limit: 5 })
  await api.getLuckyWheelInviteQuotaStats()
  assert.deepEqual(calls.map(call => call[1]), [
    '/api/luckywheel/config', '/api/luckywheel/admin/config',
    '/api/luckywheel/admin/invite-quotas', '/api/luckywheel/admin/invite-quotas',
    '/api/luckywheel/admin/invite-quota-stats',
  ])
  const admin = fs.readFileSync(path.join(root, 'src/components/WheelAdminPanel.vue'), 'utf8')
  assert.match(admin, /await getAdminLuckyWheelConfig\(\)/)
  const ordinary = fs.readFileSync(path.join(root, 'src/components/LuckyWheel.vue'), 'utf8')
  assert.match(ordinary, /await getLuckyWheelConfig\(\)/)
  assert.doesNotMatch(ordinary, /WheelInviteQuotaPanel|global_weekly_limit|personal_weekly_limit/)
})


for (const ten of [false, true]) {
  test(`ordinary wheel renders and settles name-only ${ten ? 'ten' : 'single'} results`, async () => {
    const raw = fs.readFileSync(path.join(root, 'src/components/LuckyWheel.vue'), 'utf8')
    const parsed = parse(raw)
    assert.deepEqual(parsed.errors, [])
    const source = parsed.descriptor.script.content.replace(/^import .*$/gm, '').replace('export default', 'module.exports =')
    const events = []
    const result = { item: { name: '积分 +10' }, credits_change: 10, current_credits: 100, used_free_spin: true, free_spin_source: 'gift_pack' }
    const context = {
      module: { exports: {} },
      console: { log() {}, warn() {}, error() {} },
      setTimeout: callback => callback(),
      formatMsShortDateTime: value => String(value),
      getLuckyWheelConfig: async () => ({ data: { items: [{ name: '积分 +10' }, { name: '邀请码 1 枚' }], cost_credits: 10, min_credits_required: 30 } }),
      getBlackjackFreeSpins: async () => ({ data: { available: 1, expires_at_ms_list: [1234] } }),
      spinLuckyWheel: async () => ({ data: result }),
      spinLuckyWheelTenTimes: async () => ({ data: { results: Array.from({ length: 10 }, () => result), current_credits: 100, total_credits_change: 100 } }),
    }
    vm.runInNewContext(source, context)
    const options = context.module.exports
    const state = { ...options.data(), disabled: false, userCredits: 1000, $nextTick: fn => fn(), $emit: (...args) => events.push(args) }
    for (const [name, method] of Object.entries(options.methods)) state[name] = method.bind(state)
    for (const [name, get] of Object.entries(options.computed)) Object.defineProperty(state, name, { get: get.bind(state) })
    await state.loadWheelConfig()
    assert.equal(state.wheelItems.length, 2)
    assert.match(state.getSectorPath(0), /^M /)
    assert.equal(state.loading, false)
    await state.callSpinAPI(ten)
    assert.equal(state.showResult, true)
    assert.equal(state.getCurrentPointingSector().item.name, '积分 +10')
    assert.equal(state.winResult.current_credits, 100)
    assert.equal(state.winResult.is_ten_spin, ten)
    assert.equal(state.winResult.used_free_spin, !ten)
    assert.equal(events.length, 1)
    if (ten) assert.equal(state.winResult.results.length, 10)
    else assert.equal(state.freeSpinSourceLabel, '礼包免费机会')
    assert.equal('probability' in state.winResult, false)
    state.disabled = true
    state.spin()
    assert.equal(events.length, 1) // Disabled admin preview cannot trigger another spin.
  })
}
