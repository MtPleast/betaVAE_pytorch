import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import numpy as np
import os

from betaVAE_dataset import return_data
from betaVAE_model import Encoder_MNIST,Decoder_MNIST,Encoder_3Dchairs,Decoder_3Dchairs,Encoder_dsprites,Decoder_dsprites
from betaVAE_show import showimg,travel_img_showimg, show_active_units

def mkdir(path):
	path=path.strip()
	path=path.rstrip("\\")
	isExists=os.path.exists(path)
	if not isExists:
		os.makedirs(path)

def recon_loss(x, x_recon):
	# loss = F.binary_cross_entropy_with_logits(x_recon, x, size_average=False).div(n)
	# loss_fn = nn.MSELoss(reduce=True, size_average=False)
	# loss = loss_fn(x,x_recon)
	loss = F.binary_cross_entropy(x_recon, x,  size_average=False)
	return loss

def kl_divergence(mu, logvar):
	kld = -0.5*(1+logvar-mu**2-logvar.exp()).sum(1).mean()
	return kld



class Solver(object):
	def __init__(self,args):
		self.z_dim = args.z_dim
		self.beta_weight = args.beta_weight

		self.data_dir = args.data_dir
		self.result_path_all_dataset = args.result_path_all_dataset
		self.datasetname = args.datasetname
		self.result_path_current_dataset = self.result_path_all_dataset[self.datasetname]

		self.shuffle = args.shuffle
		self.image_size = args.image_size
		self.batchszie = args.batchszie
		self.learning_rate = args.learning_rate
		self.train_epoch = args.train_epoch
		# 多少步画一下图、保存一下模型
		self.show_img_step = args.show_img_step
		self.save_model_step = args.save_model_step
		# load data
		self.trainloader = return_data(args)
		self.num_workers = args.num_workers
		
		self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
		print('device: ',self.device)
		# 设置encoder decoder
		if self.datasetname == 'MNIST':
			self.encoder = Encoder_MNIST(args)
			self.decoder = Decoder_MNIST(args)
		elif self.datasetname == '3Dchairs':
			self.encoder = Encoder_3Dchairs(args)
			self.decoder = Decoder_3Dchairs(args)
		elif self.datasetname == 'dsprites':
			self.encoder = Encoder_dsprites(args)
			self.decoder = Decoder_dsprites(args)

		self.encoder.to(self.device)
		self.decoder.to(self.device)

		# train 度量方式以及优化器之类
		self.train_step = 0
		self.criterion = nn.MSELoss()
		self.optimizer_encoder = optim.Adam(self.encoder.parameters(),lr=self.learning_rate)
		self.optimizer_decoder = optim.Adam(self.decoder.parameters(),lr=self.learning_rate)

		# z travese
		self.z_travese_sample_imgth = args.z_travese_sample_imgth
		self.z_travese_limit = args.z_travese_limit
		self.z_travese_interval = args.z_travese_interval
		self.z_travese_number_per_line = args.z_travese_number_per_line
		self.var_threshold = args.var_threshold
		# result
		self.generated_images_path = self.result_path_current_dataset + 'generated_images/'
		self.travese_z_path = args.load_model_path + 'travese_z_'+str(self.z_travese_sample_imgth)+'/'
		# save model
		self.save_state_path = self.result_path_current_dataset + 'save_model'
		self.load_model_path = args.load_model_path+'save_model'
		

		# 创建文件夹
		mkdir(self.result_path_current_dataset)
		mkdir(self.generated_images_path)
		mkdir(self.travese_z_path)


	def record_loss(self,loss_recon,loss_kld):
		with open(self.result_path_current_dataset+'VAE_result.txt', 'a') as f:
			f.write(str(self.train_step+1)+'\t'+str(round(loss_recon,4))+'\t'+str(round(loss_kld,4))+'\n')
			f.close()

	def reparameterizetion(self,z):
		mu= z[:,:self.z_dim]
		logvar = z[:,self.z_dim:]
		std = logvar.mul(0.5).exp_()
		eps = std.data.new(std.size()).normal_()
		return mu,logvar,eps.mul(std).add_(mu)

	def getgroundtruth(self):
		for i,img in enumerate(self.trainloader,0):
			print(i)
			img = img.squeeze()
			showimg(img,i,'groundtruth',self.datasetname,self.generated_images_path,1)


	def train(self):
		f = open(self.result_path_current_dataset+'VAE_result.txt', 'w')
		f.write('beta_VAE\n')
		f.write('dataset = '+self.datasetname+'\n')
		f.write('data shuffle = '+str(self.shuffle)+'\n')
		f.write('image_size = '+str(self.image_size)+'*'+str(self.image_size)+'\n')
		f.write('reco_loss = F.binary_cross_entropy\n')
		f.write('beta_weight = '+str(self.beta_weight)+'\n')
		f.write('z_dim = '+str(self.z_dim)+'\n')
		f.write('step\tloss_recon\tloss_kld\n')
		f.close()

		
		for epoch_count in range(self.train_epoch):
			running_loss_rec = 0.0
			running_loss_kld = 0.0
			# 使用train训练集
			for i,img in enumerate(self.trainloader,0):
				# MNIST 除去标签
				if self.datasetname == 'MNIST':
					img = img[0]
				# 对于3Dchairs 只取一个通道
				elif self.datasetname == '3Dchairs':
					img = img[:,0,:,:]
					img = img.unsqueeze(1)
				# 对于dsprites 只取一个通道
				elif self.datasetname == 'dsprites':
					pass
				
				img = img.to(self.device)
				z_en = self.encoder(img)
				# print('z_en size: ',z_en.size())
				mu,logvar,z_de = self.reparameterizetion(z_en)
				img_decoder = self.decoder(z_de)
				
				vae_recon_loss = recon_loss(img, img_decoder)
				vae_kld_loss = kl_divergence(mu, logvar)
				vae_loss = vae_recon_loss + self.beta_weight * vae_kld_loss

				self.optimizer_encoder.zero_grad()
				self.optimizer_decoder.zero_grad()
				vae_loss.backward()
				self.optimizer_encoder.step()
				self.optimizer_decoder.step()

				running_loss_rec += vae_recon_loss.item()
				running_loss_kld += vae_kld_loss.item()
				if i % self.show_img_step == self.show_img_step-1:

					# 对于不同步长时候，进行归一化除法，得到可以有意义的loss
					if i < self.show_img_step:
						temp_divend = i
					else:
						temp_divend = self.show_img_step
					
					print('[%d,%5d,%8d] loss: %3f  %3f' %(epoch_count+1 ,i+1, self.train_step+1, running_loss_rec/temp_divend , running_loss_kld/temp_divend) )
					self.record_loss(running_loss_rec/temp_divend , running_loss_kld/temp_divend)
					
					running_loss_rec = 0.0
					running_loss_kld = 0.0
					
					img = img.squeeze()
					showimg(img,self.train_step,'groundtruth',self.datasetname,self.generated_images_path,self.show_img_step)
					
					img_decoder = img_decoder.squeeze()
					# print('img_decoder: ',img_decoder)

					# numpy_img_decoder = img_decoder.detach().cpu().numpy()
					# mean_img_decoder = np.mean(numpy_img_decoder)
					# print('mean_img_decoder:  ',mean_img_decoder)

					img_decoder_01 = torch.zeros(img_decoder.size()).type_as(img_decoder)
					img_decoder_01[img_decoder >= 0.5] = 1
					
					showimg(img_decoder_01,self.train_step,'recon',self.datasetname,self.generated_images_path,self.show_img_step)
					sample_z = torch.from_numpy(np.random.normal( 0, 1, size=z_de.size()))
					sample_z = sample_z.float()
					sample_z = sample_z.to(self.device)
					sample_x = self.decoder(sample_z)
					sample_x = sample_x.squeeze()
					showimg(sample_x,self.train_step,'sample',self.datasetname,self.generated_images_path,self.show_img_step)
					

					# show active units
					show_active_units(self.z_dim, self.trainloader, self.datasetname, self.encoder, self.var_threshold)
				



				if self.train_step % self.save_model_step == self.save_model_step - 1:
					# model save
					model_state = {'encoder':self.encoder,'decoder':self.decoder}
					save_state = {'z_dim':self.z_dim,'beta_weight':self.beta_weight,'model_state':model_state}
					with open(self.save_state_path, 'wb+') as f:
						torch.save(save_state, self.save_state_path)

				self.train_step += 1

		# model save
		model_state = {'encoder':self.encoder,'decoder':self.decoder}
		save_state = {'z_dim':self.z_dim,'beta_weight':self.beta_weight,'model_state':model_state}
		with open(self.save_state_path, 'wb+') as f:
			torch.save(save_state, self.save_state_path)
		
	def loadmdoel_travese(self):
		with open(self.load_model_path, 'rb') as f:
			checkpoint = torch.load(f)
		self.z_dim = checkpoint['z_dim']
		self.beta_weight = checkpoint['beta_weight']
		self.encoder = checkpoint['model_state']['encoder']
		self.decoder = checkpoint['model_state']['decoder']
		print('z_dim:',self.z_dim)
		print('beta_weight:',self.beta_weight)

		# 输出有几个active的units
		show_active_units(self.z_dim, self.trainloader, self.datasetname, self.encoder, self.var_threshold)

		print('travel start')
		x_sample = self.trainloader.dataset.__getitem__(self.z_travese_sample_imgth)[0]
		# print('x_sample: ',x_sample.size())
		x_sample = x_sample.unsqueeze(0)

		if self.datasetname == '3Dchairs':
			x_sample = x_sample.unsqueeze(1)
		elif self.datasetname == 'dsprites':
			x_sample = x_sample.unsqueeze(1)

		x_sample = x_sample.to(self.device)
		z_sample = self.encoder(x_sample)[:, :self.z_dim]
		
		print('z_sample',z_sample)
		# 每个维度travese多少个图片出来
		limit_count = int(2*self.z_travese_limit/self.z_travese_interval)
		z_sample = z_sample.repeat(limit_count,1)
		interpolation = torch.arange(-self.z_travese_limit, self.z_travese_limit, self.z_travese_interval)	
		for i in range(self.z_dim):
			z_travel = z_sample.clone()
			z_travel[:,i] = interpolation
			print(i)
			x_travel = self.decoder(z_travel)
			x_travel = x_travel.squeeze()
			travel_img_showimg(x_travel,i,limit_count,self.datasetname,self.travese_z_path,self.z_travese_number_per_line)




	# # test load model
	# def loadmdoel_savemodel(self):

	# 	with open(self.load_model_path, 'rb') as f:
	# 		checkpoint = torch.load(f)
	# 	self.z_dim = checkpoint['z_dim']
	# 	self.beta_weight = checkpoint['beta_weight']
	# 	self.encoder.load_state_dict(checkpoint['model_state']['encoder'])
	# 	self.decoder.load_state_dict(checkpoint['model_state']['decoder'])
	# 	print('z_dim:',self.z_dim)
	# 	print('beta_weight:',self.beta_weight)
	# 	# model save
	# 	model_state = {'encoder':self.encoder,'decoder':self.decoder}
	# 	save_state = {'z_dim':self.z_dim,'beta_weight':self.beta_weight,'model_state':model_state}

	# 	with open('E:/pytorch_VAE_result/3Dchairs/3Dchairs_result/travese_z/save_model', 'wb+') as f:
	# 		torch.save(save_state, 'E:/pytorch_VAE_result/3Dchairs/3Dchairs_result/travese_z/save_model')

	# def loadmdoel(self):
	# 	with open('E:/pytorch_VAE_result/3Dchairs/3Dchairs_result/travese_z/save_model', 'rb') as f:
	# 		checkpoint = torch.load(f)
	# 	self.z_dim = checkpoint['z_dim']
	# 	self.beta_weight = checkpoint['beta_weight']
	# 	self.encoder = checkpoint['model_state']['encoder']
	# 	self.decoder = checkpoint['model_state']['decoder']

	# 	print('z_dim:',self.z_dim)
	# 	print('beta_weight:',self.beta_weight)

	# 	print('travel start')
	# 	x_sample = self.trainloader.dataset.__getitem__(self.z_travese_sample_imgth)[0]
	# 	x_sample = x_sample.unsqueeze(0)
	# 	if self.datasetname == '3Dchairs':
	# 		x_sample = x_sample.unsqueeze(1)
	# 	x_sample = x_sample.to(self.device)
	# 	z_sample = self.encoder(x_sample)[:, :self.z_dim]
		
	# 	print('z_sample',z_sample)
	# 	# 每个维度travese多少个图片出来
	# 	limit_count = int(2*self.z_travese_limit/self.z_travese_interval)
	# 	z_sample = z_sample.repeat(limit_count,1)
	# 	interpolation = torch.arange(-self.z_travese_limit, self.z_travese_limit, self.z_travese_interval)	
	# 	for i in range(self.z_dim):
	# 		z_travel = z_sample.clone()
	# 		print('z_travel: ',z_travel.size())
	# 		z_travel[:,i] = interpolation
	# 		# print(z_travel,'\n\n\n')
	# 		print(i)
	# 		x_travel = self.decoder(z_travel)
	# 		x_travel = x_travel.squeeze()
	# 		travel_img_showimg(x_travel,i,limit_count,self.datasetname,self.travese_z_path)