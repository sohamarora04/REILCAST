-- Wireshark dissector for the ReliCast wire format (relicast/proto.py).
-- Header (24 bytes, network order): magic "RC"(2) type(1) flags(1) session(4) seq(4) total(4) ts_us(8)
-- Install: copy to the Wireshark personal plugins folder (Help > About Wireshark > Folders > Personal Lua Plugins)
-- or run:  wireshark -X lua_script:demo/relicast.lua capture.pcap
-- Registered as a heuristic dissector on UDP, so the random data port needs no "Decode As".
local rc = Proto("relicast", "ReliCast")

local TYPES = { [1] = "DATA", [2] = "REPAIR", [3] = "HEARTBEAT", [4] = "NACK", [5] = "FIN", [6] = "PROBE" }

local f_magic   = ProtoField.string("relicast.magic", "Magic")
local f_type    = ProtoField.uint8("relicast.type", "Type", base.DEC, TYPES)
local f_flags   = ProtoField.uint8("relicast.flags", "Flags", base.HEX)
local f_session = ProtoField.uint32("relicast.session", "Session", base.HEX)
local f_seq     = ProtoField.uint32("relicast.seq", "Sequence / chunk")
local f_total   = ProtoField.uint32("relicast.total", "Total chunks")
local f_ts      = ProtoField.uint64("relicast.ts_us", "Sender timestamp (us, SNTP-corrected)")
local f_len     = ProtoField.uint32("relicast.payload_len", "Payload length")
local f_nrid    = ProtoField.uint32("relicast.nack.rid", "NACK receiver id")
local f_nn      = ProtoField.uint16("relicast.nack.ranges", "NACK range count")
local f_nrange  = ProtoField.string("relicast.nack.range", "Missing range")

rc.fields = { f_magic, f_type, f_flags, f_session, f_seq, f_total, f_ts, f_len, f_nrid, f_nn, f_nrange }

local HDR_LEN = 24

local function dissect(buf, pinfo, tree)
  if buf:len() < HDR_LEN then return false end
  if buf(0, 2):string() ~= "RC" then return false end

  local ptype = buf(2, 1):uint()
  local t = tree:add(rc, buf(0, buf:len()), "ReliCast " .. (TYPES[ptype] or "?"))
  t:add(f_magic, buf(0, 2))
  t:add(f_type, buf(2, 1))
  t:add(f_flags, buf(3, 1))
  t:add(f_session, buf(4, 4))
  t:add(f_seq, buf(8, 4))
  t:add(f_total, buf(12, 4))
  t:add(f_ts, buf(16, 8))
  local plen = buf:len() - HDR_LEN
  t:add(f_len, plen):set_generated()

  local seq = buf(8, 4):uint()
  local info = (TYPES[ptype] or "?")
  if ptype == 1 or ptype == 2 then
    info = info .. " chunk " .. seq .. "/" .. buf(12, 4):uint()
  elseif ptype == 3 then
    info = info .. " highest=" .. seq
  elseif ptype == 4 and plen >= 6 then
    local rid = buf(HDR_LEN, 4):uint()
    local n = buf(HDR_LEN + 4, 2):uint()
    local nt = t:add(rc, buf(HDR_LEN, plen), "NACK body")
    nt:add(f_nrid, buf(HDR_LEN, 4))
    nt:add(f_nn, buf(HDR_LEN + 4, 2))
    local shown = {}
    for i = 0, n - 1 do
      local off = HDR_LEN + 6 + i * 8
      if off + 8 > buf:len() then break end
      local a, b = buf(off, 4):uint(), buf(off + 4, 4):uint()
      nt:add(f_nrange, buf(off, 8), a .. "-" .. b)
      if #shown < 3 then shown[#shown + 1] = a .. "-" .. b end
    end
    info = info .. " from rid " .. rid .. " missing " .. table.concat(shown, ",") .. (n > 3 and ",..." or "")
  end
  pinfo.cols.protocol = "RELICAST"
  pinfo.cols.info = info
  return true
end

function rc.dissector(buf, pinfo, tree)
  if not dissect(buf, pinfo, tree) then return 0 end
  return buf:len()
end

rc:register_heuristic("udp", function(buf, pinfo, tree)
  return dissect(buf, pinfo, tree)
end)
