#!/usr/bin/env python

"""
Copyright (C) 2019-2020 Elliott Mitchell

	This program is free software: you can redistribute it and/or
	modify it under the terms of the GNU General Public License as
	published by the Free Software Foundation, either version 3 of
	the License, or (at your option) any later version.

	This program is distributed in the hope that it will be useful,
	but WITHOUT ANY WARRANTY; without even the implied warranty of
	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
	GNU General Public License for more details.

	You should have received a copy of the GNU General Public
	License along with this program.  If not, see
	<http://www.gnu.org/licenses/>.

$Id: 2e91bcb1f46c899bfa157ad452d3d6c7b7796839 $
"""

from __future__ import print_function

import sys
import io
import struct

from collections import deque

from PIL import Image


imageheaderfmt = struct.Struct("<40s6L")

headerfmt = struct.Struct("<16s2L16s1L")


__tochr = struct.Struct("B")
def tochr(ch):
	return __tochr.pack(ch)


class RRImage:

	# where our source material comes from
	input = None

	# the destination
	output = None

	# kind of important factor
	blocksize = None

	# for images which need delayed handling (merge candidates)
	delayed = []

	# table of potential merging candidates
	mergetab = {}

	# end of area used so far
	used = None

	def __init__(self, offset, name, dataoffset, expect, width, height, offsetX, offsetY):
		self.offset=offset
		self.name=name
		self.dataoffset=dataoffset
		self.expect=expect
		self.width=width
		self.height=height
		self.offsetX=offsetX
		self.offsetY=offsetY

	# initialized shared values
	@staticmethod
	def startup(input, output, blocksize):
		RRImage.input = input
		RRImage.output = output
		RRImage.blocksize = blocksize
		RRImage.used = blocksize<<1

	@staticmethod
	def entry(offset):
		RRImage.input.seek(offset)

		header = RRImage.input.read(imageheaderfmt.size)

		if len(header) != imageheaderfmt.size:
			print("Failed while attempting to read header at offset 0x{:04X}".format(offset))
			sys.exit(1)

		name, dataoffset, expect, width, height, offsetX, offsetY = imageheaderfmt.unpack(header)
		name = name.rstrip(b'\x00').decode("ascii")

		if len(name)<=0:
			return False

		later = False

		if "powered_android_image" in name:
			later = True
			key = None
		elif "1st" in name:
			later = True
			part = name.partition("1st")
			key = part[0]+part[2]
		elif "2nd" in name:
			later = True
			part = name.partition("2nd")
			key = part[0]+part[2]
#		elif "system_recovery_menu_image" in name:
#			later = True
#			key = "factory_reset__line_image"

		entry = RRImage(offset, name, dataoffset, expect, width, height, offsetX, offsetY)

		if later:
			if key in RRImage.mergetab:
				RRImage.mergetab[key].merge(key, entry)
			else:
				RRImage.delayed.append(entry)
				if key:
					RRImage.mergetab[key] = entry
					entry.merge(key, entry)

		else:
			entry.load()
			entry.shrink()
			entry.finish()


	@staticmethod
	def dologo(image):
		self = RRImage
		logo = self.logo

		logo.offsetX += (logo.width-image.width)//2
		logo.offsetY += (logo.height-image.height)//2

		if logo.offsetX < 0:
			print("WARNING: New logo is wider than display, corruption likely!", file=sys.stderr)
			logo.offsetX = 0
		if logo.offsetY < 0:
			print("WARNING: New logo is taller than display, corruption likely!", file=sys.stderr)
			logo.offsetY = 0

		logo.width = image.width
		logo.height = image.height

		data = image.getdata()

		logo.payload = b''
		count = 0
		prev = (data[0][0]^1, 0, 0)

		for p in data:
			if p == prev:
				count += 1

				if count > 255:
					logo.payload += b'\xFF' + tochr(p[2]) + tochr(p[1]) + tochr(p[0])
					count -= 255

			else:
				logo.payload += tochr(count) + tochr(prev[2]) + tochr(prev[1]) + tochr(prev[0])
				count = 1
				prev = p

		if count > 0:
			if count > 255:
				logo.payload += b'\xFF' + tochr(prev[2]) + tochr(prev[1]) + tochr(prev[0])
				count -= 255
			logo.payload += tochr(count) + tochr(prev[2]) + tochr(prev[1]) + tochr(prev[0])
		logo.payload = logo.payload[4:]

		logo.finish()


	@staticmethod
	def late():
		for entr in RRImage.delayed:
			entr.dolate()


	def dolate(self):
		try:
			if len(self.mergers) <= 1:
				raise AttributeError()
		except AttributeError:
			RRImage.logo = self
			return

		other = self.mergers[1]

		self.load()
		other.load()

		# Easier case, complete overlap
		if self.payload == other.payload:
			self.shrink()
			self.finish()

			other.width = self.width
			other.height = self.height

			other.offsetX += self.removedleft
			other.offsetY += self.removedtop

			header = imageheaderfmt.pack(other.name.encode("ascii"), self.used, len(self.payload), other.width, other.height, other.offsetX, other.offsetY)

			other.output.seek(other.offset)
			other.output.write(header)

		# Harder case, incomplete overlap
		else:
			self.splitpayload()
			other.splitpayload()

			check = self.height if self.height <= other.height else other.height

			for l in range(check):
				if self.payload[l] != other.payload[l]:
					RRImage.delayed.append(other)
					return

			# sharing common header

			if self.height <= other.height:
				small = self
				large = other
			else:
				large = self
				small = other

			large._shrink()
			small.removebottom()

			small.offsetY += large.removedtop
			small.offsetX += large.removedleft
			small.width = large.width

			small.height -= large.removedtop

			if small.height > large.height - small.height:
				small.payload = large.payload
				large.payload = deque()
				while len(small.payload) > small.height:
					large.payload.appendleft(small.payload.pop())
			else:
				small.payload = deque()
				while len(small.payload) < small.height:
					small.payload.append(large.payload.popleft())

			small.joinpayload()
			large.joinpayload()

			large.used += large.blocksize-1
			large.used &= ~(large.blocksize-1)
			small.used = large.used

			large.output.seek(large.used)
			large.output.write(small.payload)
			large.output.write(large.payload)

			small.payload = len(small.payload)
			large.payload = small.payload + len(large.payload)
			RRImage.used = large.used + large.payload

			header = imageheaderfmt.pack(self.name.encode("ascii"), self.used, self.payload, self.width, self.height, self.offsetX, self.offsetY)

			self.output.seek(self.offset)
			self.output.write(header)

			header = imageheaderfmt.pack(other.name.encode("ascii"), other.used, other.payload, other.width, other.height, other.offsetX, other.offsetY)

			other.output.seek(other.offset)
			other.output.write(header)


	def merge(self, key, other):
		try:
			self.mergers.append(other)
		except AttributeError:
			self.mergers = [other]
			self.key = key


	def load(self):
		self.input.seek(self.dataoffset)
		self.payload = self.input.read(self.expect)


	def shrink(self):
		self.splitpayload()

		self._shrink()

		self.joinpayload()

	def _shrink(self):
		self.removetop()

		self.removebottom()

		self.removeleft()

		self.removeright()


	def finish(self):
		# align to blocksize
		self.used += self.blocksize-1
		self.used &= ~(self.blocksize-1)

		header = imageheaderfmt.pack(self.name.encode("ascii"), self.used, len(self.payload), self.width, self.height, self.offsetX, self.offsetY)

		self.output.seek(self.used)
		self.output.write(self.payload)

		RRImage.used = self.used + len(self.payload)

		self.output.seek(self.offset)
		self.output.write(header)


	def splitpayload(self):

		payload = deque()

		while self.payload:
			count = ord(self.payload[0:1])
			current = 0
			while count < self.width and len(self.payload) > current+4:
				current += 4
				count += ord(self.payload[current:current+1])
			payload.append(self.payload[:current])
			if count == self.width:
				payload[-1] += self.payload[current:current+4]
				self.payload = self.payload[current+4:]
			elif count > self.width:
				count -= self.width
				payload[-1] += tochr(ord(self.payload[current:current+1])-count)+self.payload[current+1:current+4]
				self.payload = tochr(count)+self.payload[current+1:]
			else:
				payload.pop()
				self.payload = b''
				print('Warning, payload for "{:s}" was wrong length!'.format(self.name), file=sys.stderr)

		# Potentially caused by other tools screwing up
		if len(payload) < self.height:
			print('Found insufficient payload data for "{:s}"'.format(self.name), file=sys.stderr)
			self.height = len(payload)
		# Yes, this really has been seen in nature
		if len(payload) > self.height:
			print('Found excess payload data for "{:s}"'.format(self.name), file=sys.stderr)
			while len(payload) > self.height:
				payload.pop()

		self.payload = payload


	def joinpayload(self):

		payload = self.payload

		pixel = payload[0][-3:]
		count = ord(payload[0][-4:-3])
		self.payload = payload.popleft()[:-4]

		while payload:
			if count > 255:
				self.payload += b'\xFF' + pixel
				count -= 255
			elif payload[0][1:3] == pixel:
				count += ord(payload[0][0:1])
				payload[0] = payload[0][4:]
				if not payload[0]:
					payload.popleft()
			else:
				self.payload += tochr(count) + pixel
				pixel = payload[0][-3:]
				count = ord(payload[0][-4:-3])
				self.payload += payload.popleft()[:-4]

		if count:
			if count > 255:
				self.payload += b'\xFF' + pixel
				count -= 255
			self.payload += tochr(count) + pixel


	def removetop(self):

		self.removedtop = 0

		payload = self.payload

		pixel = payload[0][1:4]
		for x in range(5, len(payload[0]), 4):
			if payload[0][x:x+3] != pixel:
				break
		else:
			while pixel:
				for x in range(1, len(payload[1]), 4):
					if payload[1][x:x+3] != pixel:
						pixel = None
						break
				else:
					payload.popleft()
					self.offsetY += 1
					self.height -= 1
					self.removedtop += 1

		self.payload = payload


	def removebottom(self):

		self.removedbottom = 0

		payload = self.payload

		pixel = payload[-1][1:4]
		for x in range(5, len(payload[-1]), 4):
			if payload[-1][x:x+3] != pixel:
				break
		else:
			while pixel:
				for x in range(1, len(payload[-2]), 4):
					if payload[-2][x:x+3] != pixel:
						pixel = None
						break
				else:
					payload.pop()
					self.height -= 1
					self.removedbottom += 1

		self.payload = payload


	def removeleft(self):

		self.removedleft = 0

		payload = self.payload

		pixel = payload[0][1:4]
		max = ord(payload[0][0:1])
		for x in range(4, len(payload[0]), 4):
			if payload[0][x+1:x+4] != pixel:
				max -= 1
				break
			max += ord(payload[0][x:x+1])

		for y in range(1, len(payload)):
			cur = 0
			for x in range(0, len(payload[y]), 4):
				if payload[y][x+1:x+4] != pixel:
					max = cur - 1
					break
				cur += ord(payload[y][x:x+1])
				if cur >= max:
					break

		if max < 0:
			max = 0

		for y in range(0, len(payload)):
			cur = max
			for x in range(0, len(payload[y]), 4):
				if ord(payload[y][x:x+1]) == cur:
					payload[y] = payload[y][x+4:]
					break
				elif ord(payload[y][x:x+1]) > cur:
					payload[y] = tochr(ord(payload[y][x:x+1])-cur) + payload[y][x+1:]
					break
				cur -= ord(payload[y][x:x+1])

		self.offsetX += max
		self.width -= max
		self.removedleft += max

		self.payload = payload


	def removeright(self):

		self.removedright = 0

		payload = self.payload

		pixel = payload[0][-3:]
		max = ord(payload[0][-4:-3])
		for x in range(len(payload[0])-8, -1, -4):
			if payload[0][x+1:x+4] != pixel:
				max -= 1
				break
			max += ord(payload[0][x:x+1])

		for y in range(1, len(payload)):
			cur = 0
			for x in range(len(payload[y])-4, -1, -4):
				if payload[y][x+1:x+4] != pixel:
					max = cur - 1
					break
				cur += ord(payload[y][x:x+1])
				if cur >= max:
					break

		if max < 0:
			max = 0

		for y in range(0, len(payload)):
			cur = max
			for x in range(len(payload[y])-4, -1, -4):
				if ord(payload[y][x:x+1]) == cur:
					payload[y] = payload[y][:x]
					break
				elif ord(payload[y][x:x+1]) > cur:
					payload[y] = payload[y][:x] + tochr(ord(payload[y][x:x+1])-cur) + payload[y][x+1:x+4]
					break
				cur -= ord(payload[y][x:x+1])

		self.width -= max
		self.removedright += max

		self.payload = payload


if __name__ == "__main__":
	if len(sys.argv) == 4:
		try:
			output = io.open(sys.argv[3], "wb")
		except IOError as err:
			print('Failed while opening output file "{:s}": {:s}'.format(sys.argv[3], str(err)), file=sys.stderr)
			sys.exit(1)
	elif len(sys.argv) != 3:
		print("Usage: {:s} <new logo> <input file> [<output file>]".format(sys.argv[0]), file=sys.stderr)
		sys.exit(1)
	else:
		try:
			output = io.open(sys.argv[2]+".out", "wb")
		except IOError as err:
			print('Failed while opening output file "{:s}": {:s}'.format(sys.argv[2]+".out", str(err)), file=sys.stderr)
	try:
		input = io.open(sys.argv[2], "rb")
	except IOError as err:
		print('Failed while opening input file "{}": {}'.format(sys.argv[2], str(err)), file=sys.stderr)
		sys.exit(1)

	header = input.read(headerfmt.size)
	if len(header) != headerfmt.size:
		print("Failed while attempting to read starting raw_resources header", file=sys.stderr)
		sys.exit(1)

	magic, count, unknown, dev, dataend = headerfmt.unpack(header)



	if magic != b'BOOT_IMAGE_RLE\x00\x00':
		print('Bad magic number (unknown format): {}'.format(magic.rstrip('\x00')), file=sys.stderr)
		sys.exit(1)

	print('Found magic string "BOOT_IMAGE_RLE"\n')


	print('Target device: "{}"'.format(dev.rstrip(b'\x00').decode("ascii")))


	# probe the size
	for shift in range(9,20):
		blocksize = 1<<shift
		input.seek(blocksize)

		header = input.read(imageheaderfmt.size)
		if len(header) != imageheaderfmt.size:
			print("Failed while attempting to probe at shift {:d} (blocksize {:d})".format(shift, blocksize), file=sys.stderr)
			sys.exit(1)

		name = imageheaderfmt.unpack(header)[0].rstrip(b'\x00').decode("ascii")

		if len(name)>0:
			break
	else:
		print("Probing failed to find image headers/blocksize", file=sys.stderr)
		sys.exit(1)

	print("Probe found a blocksize of {:d} (shift={:d})".format(blocksize, shift))

	RRImage.startup(input, output, blocksize)


	for offset in range(blocksize, blocksize+count*imageheaderfmt.size, imageheaderfmt.size):
		RRImage.entry(offset)

	RRImage.late()



	try:
		newlogo = Image.open(sys.argv[1], "r")
		newlogo.convert(mode="RGB")
	except IOError as err:
		print('Failed while opening new logo file "{}": {}'.format(sys.argv[1], str(err)), file=sys.stderr)
		sys.exit(1)

	RRImage.dologo(newlogo)



	header = headerfmt.pack(magic, count, unknown, dev, RRImage.used)
	output.seek(0)
	output.write(header)
	output.close()

