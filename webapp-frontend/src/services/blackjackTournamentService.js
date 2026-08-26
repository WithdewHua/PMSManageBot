// 21 点锦标赛相关服务
import { apiClient } from '../main'

const base = '/api/blackjack/tournament'

// 赛事列表。默认只给报名中与进行中的赛事（大厅口径）；
// includeFinished 时连已结算与已取消一并列出，供管理员回看
export const listBlackjackTournaments = ({ includeFinished = false } = {}) => {
  return apiClient.get(base, {
    params: includeFinished ? { include_finished: true } : {}
  })
}

export const getBlackjackTournament = (tournamentId) => {
  return apiClient.get(`${base}/${tournamentId}`)
}

// 全场排名。进行中给临时位次，已结算给最终名次
export const getBlackjackTournamentStandings = (tournamentId) => {
  return apiClient.get(`${base}/${tournamentId}/standings`)
}

// 报名：扣报名费换取赛内筹码。满员时本次报名会触发开赛
export const registerBlackjackTournament = (tournamentId) => {
  return apiClient.post(`${base}/${tournamentId}/register`)
}

// 赛内当前手牌与筹码状态，用于进入牌桌时恢复
export const getCurrentTournamentHand = (tournamentId) => {
  return apiClient.get(`${base}/${tournamentId}/current`)
}

// 赛内发牌。注额为**筹码**，须在区间内且为步进的整数倍
export const dealTournamentHand = (tournamentId, betChips) => {
  return apiClient.post(`${base}/${tournamentId}/deal`, { bet_chips: betChips })
}

export const hitTournamentHand = (tournamentId, handId) => {
  return apiClient.post(`${base}/${tournamentId}/hand/${handId}/hit`)
}

export const standTournamentHand = (tournamentId, handId) => {
  return apiClient.post(`${base}/${tournamentId}/hand/${handId}/stand`)
}

export const doubleTournamentHand = (tournamentId, handId) => {
  return apiClient.post(`${base}/${tournamentId}/hand/${handId}/double`)
}

export const surrenderTournamentHand = (tournamentId, handId) => {
  return apiClient.post(`${base}/${tournamentId}/hand/${handId}/surrender`)
}

// 以下仅管理员可用
export const createBlackjackTournament = (payload) => {
  return apiClient.post(`${base}/admin/create`, payload)
}

export const updateBlackjackTournament = (tournamentId, payload) => {
  return apiClient.put(`${base}/admin/${tournamentId}`, payload)
}

// 取消赛事并全额退还报名费。仅报名中的赛事可取消
export const cancelBlackjackTournament = (tournamentId) => {
  return apiClient.post(`${base}/admin/${tournamentId}/cancel`)
}

// 比对 entrant_count 与 entry 实际行数。前者是奖池推导的因子，
// 一旦漂移会直接影响派奖金额，故提供一处显式校验
export const checkBlackjackTournamentConsistency = (tournamentId) => {
  return apiClient.get(`${base}/admin/${tournamentId}/consistency`)
}
